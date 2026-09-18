"""Browser endpoint for deleting unsubmitted delivery uploads."""

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse

from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import (
    parse_positive_identifier_list,
)
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import (
    remove_user_delivery_upload,
)


def delivery_delete(request):
    """Delete owned, unsubmitted deliveries, their uploads, and QC history."""

    try:
        delivery_ids = parse_positive_identifier_list(request.POST.get("ids"))
    except IdentifierListError as exc:
        return _error_response(exc.code, exc.message, status=400)

    account_access = access_for_request(request)
    with transaction.atomic():
        deliveries_by_id = {
            delivery.id: delivery
            for delivery in models.Delivery.objects.select_for_update(
                of=("self",)
            )
            .filter(id__in=delivery_ids, is_deleted=False)
            .select_related("user")
            .order_by("id")
        }
        if len(deliveries_by_id) != len(delivery_ids):
            return _error_response(
                "delivery_not_found",
                "One or more selected deliveries do not exist.",
                status=404,
            )
        if any(
            not account_access.can_manage_user(
                deliveries_by_id[delivery_id].user_id
            )
            for delivery_id in delivery_ids
        ):
            return _error_response(
                "object_permission_denied",
                "The account cannot delete one or more selected deliveries.",
                status=403,
            )
        if _has_active_job(delivery_ids):
            return _error_response(
                "delivery_has_active_job",
                "A selected delivery has a waiting or running QC job.",
                status=409,
            )
        if _has_submission(delivery_ids, deliveries_by_id):
            return _error_response(
                "delivery_has_submission",
                "A submitted delivery is retained as audit history.",
                status=409,
            )

        upload_error = _remove_local_uploads(delivery_ids, deliveries_by_id)
        if upload_error is not None:
            return upload_error

        # Keep job history until this explicit delivery deletion. Replacements
        # also retire delivery rows, but must retain their previous QC evidence.
        # The parent locks serialize this cleanup with QC and submission writes.
        models.Job.objects.filter(delivery_id__in=delivery_ids).delete()
        models.Delivery.objects.filter(id__in=delivery_ids).update(
            is_deleted=True
        )

    return JsonResponse(
        {
            "status": "ok",
            "message": "{:d} deliveries have been deleted.".format(
                len(delivery_ids)
            ),
        }
    )


def _has_active_job(delivery_ids):
    return models.Job.objects.filter(
        delivery_id__in=delivery_ids,
        job_status__in=(JOB_WAITING, JOB_RUNNING),
    ).exists()


def _has_submission(delivery_ids, deliveries_by_id):
    return any(
        deliveries_by_id[delivery_id].date_submitted is not None
        for delivery_id in delivery_ids
    ) or models.DeliverySubmission.objects.filter(
        delivery_id__in=delivery_ids
    ).exists()


def _remove_local_uploads(delivery_ids, deliveries_by_id):
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
            return _error_response(
                exc.code,
                exc.message,
                status=exc.status_code,
            )
    return None


def _error_response(code, message, *, status):
    return JsonResponse(
        {"status": "error", "code": code, "message": message},
        status=status,
    )
