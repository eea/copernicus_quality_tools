"""Delivery lifecycle and submission endpoints."""

import logging
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.utils import timezone
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.services.deliveries.submission import submit_job
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import remove_user_delivery_upload
from qc_tool.frontend.dashboard.services.uploads import resolve_user_delivery_upload
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import parse_positive_identifier_list

logger = logging.getLogger(__name__)


def delivery_delete(request):
    """
    Deletes a delivery from the database and deleted the associated ZIP file from the filesystem.
    """
    try:
        delivery_ids = parse_positive_identifier_list(request.POST.get("ids"))
    except IdentifierListError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    deliveries_by_id = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    if len(deliveries_by_id) != len(delivery_ids):
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_not_found",
                "message": "One or more selected deliveries do not exist.",
            },
            status=404,
        )

    account_access = access_for_request(request)
    if any(
        not account_access.can_manage_user(deliveries_by_id[delivery_id].user_id)
        for delivery_id in delivery_ids
    ):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot delete one or more selected deliveries.",
            },
            status=403,
        )

    active_job = models.Job.objects.filter(
        delivery_id__in=delivery_ids,
        job_status__in=(JOB_WAITING, JOB_RUNNING),
    ).values_list("job_status", flat=True).first()
    if active_job is not None:
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_has_active_job",
                "message": "A selected delivery has a waiting or running QC job.",
            },
            status=409,
        )

    for delivery_id in delivery_ids:
        delivery = deliveries_by_id[delivery_id]
        if delivery.s3_id:
            continue
        try:
            remove_user_delivery_upload(
                media_root=settings.MEDIA_ROOT,
                username=delivery.user.username,
                filename=delivery.filename,
            )
        except DeliveryUploadPathError as exc:
            return JsonResponse(
                {"status": "error", "code": exc.code, "message": exc.message},
                status=exc.status_code,
            )

    models.Delivery.objects.filter(id__in=delivery_ids).update(is_deleted=True)
    return JsonResponse(
        {
            "status": "ok",
            "message": "{:d} deliveries have been deleted.".format(
                len(delivery_ids)
            ),
        }
    )


def submit_delivery_to_eea(request):
    if not settings.SUBMISSION_ENABLED:
        return _submission_disabled_response()
    if request.method == "POST":
        try:
            delivery_id = parse_positive_identifier_list(
                request.POST.get("id"),
                maximum_items=1,
            )[0]
        except IdentifierListError as exc:
            return JsonResponse(
                {"status": "error", "code": exc.code, "message": exc.message},
                status=400,
            )

        # Check if delivery with given ID exists.
        try:
            d = models.Delivery.objects.get(id=delivery_id)
        except ObjectDoesNotExist:
            response = JsonResponse({"status": "error",
                                     "message": "Delivery id={0} cannot be found in the database.".format(delivery_id)})
            response.status_code = 404
            return response
        filename = d.filename

        if not access_for_request(request).can_manage_user(d.user_id):
            return JsonResponse(
                {"status": "error", "message": "Delivery belongs to another user."},
                status=403,
            )

        try:
            logger.debug("delivery_submit_eea id=" + str(delivery_id))

            # zip_filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)

            job = d.get_submittable_job()
            if job is None:
                message = "Delivery {:s} cannot be submitted to EEA. Status is not OK.)".format(d.filename)
                response = JsonResponse({"status": "error", "message": message})
                response.status_code = 400
                return response
            submission_date = timezone.now()

            if d.s3:
                submit_job(job.job_uuid, None, CONFIG["submission_dir"], submission_date, is_s3=True)
            else:
                zip_filepath = resolve_user_delivery_upload(
                    d.filename,
                    media_root=settings.MEDIA_ROOT,
                    username=d.user.username,
                )
                submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)


            # submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date)
            d.submit()
            d.submission_date = submission_date
            d.save()
        except DeliveryUploadPathError as exc:
            d.date_submitted = None
            d.save()
            return JsonResponse(
                {
                    "status": "error",
                    "code": exc.code,
                    "message": exc.message,
                },
                status=exc.status_code,
            )
        except Exception:
            d.date_submitted = None
            d.save()
            logger.exception("Failed to submit delivery id=%s.", d.id)
            return JsonResponse(
                {
                    "status": "error",
                    "code": "submission_failed",
                    "message": "The delivery could not be submitted.",
                },
                status=500,
            )

        return JsonResponse({"status":"ok",
                             "message": "Delivery {0} successfully submitted to EEA.".format(filename)})


def submit_deliveries_to_eea_batch(request):
    if not settings.SUBMISSION_ENABLED:
        return _submission_disabled_response()
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        delivery_ids = parse_positive_identifier_list(request.POST.get("ids"))
    except IdentifierListError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )
    submitted_ids = []
    failed_details = [] # Store reasons for failure
    account_access = access_for_request(request)

    for delivery_id in delivery_ids:
        display_name = "Delivery ID {}".format(delivery_id)
        try:
            d = models.Delivery.objects.get(id=delivery_id)
            display_name = d.filename
            if not account_access.can_manage_user(d.user_id):
                failed_details.append(f"{display_name}: Delivery belongs to another user")
                continue

            # Check status logic
            job = d.get_submittable_job()
            if job is None:
                failed_details.append(f"{display_name}: Status not OK")
                continue # Move to the next delivery, don't stop the whole process

            submission_date = timezone.now()

            # Submission execution
            if d.s3:
                submit_job(job.job_uuid, None, CONFIG["submission_dir"], submission_date, is_s3=True)
            else:
                zip_filepath = resolve_user_delivery_upload(
                    d.filename,
                    media_root=settings.MEDIA_ROOT,
                    username=d.user.username,
                )
                submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)

            # Update record
            d.submit()
            d.submission_date = submission_date
            d.save()
            submitted_ids.append(delivery_id)

        except ObjectDoesNotExist:
            failed_details.append(f"ID {delivery_id}: Not found")
        except DeliveryUploadPathError as exc:
            logger.warning(
                "Rejected unsafe submission path for delivery id=%s (%s).",
                delivery_id,
                exc.code,
            )
            failed_details.append(f"{display_name}: Delivery file is unavailable")
        except Exception:
            logger.exception("Failed to submit delivery id=%s.", delivery_id)
            failed_details.append(f"{display_name}: System error")

    # --- Final Response Logic ---
    total_requested = len(delivery_ids)
    total_submitted = len(submitted_ids)

    if total_submitted == 0:
        return JsonResponse({
            "status": "error",
            "message": "None of the deliveries could be submitted.",
            "details": failed_details
        }, status=400)

    return JsonResponse({
        "status": "ok",
        "message": f"{total_submitted}/{total_requested} deliveries successfully submitted.",
        "failed": failed_details
    })


def _submission_disabled_response():
    """Return one stable contract when EEA submission is not configured."""

    return JsonResponse(
        {
            "status": "error",
            "code": "submission_disabled",
            "message": "Delivery submission is not enabled.",
        },
        status=503,
    )
