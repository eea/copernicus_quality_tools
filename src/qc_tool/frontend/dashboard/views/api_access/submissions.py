"""API delivery submission endpoints."""

import logging
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.utils import timezone
import qc_tool.frontend.dashboard.models as models
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.deliveries.submission import submit_job
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import positive_identifier
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import resolve_user_delivery_upload
from qc_tool.frontend.dashboard.views.deliveries.actions import (
    _submission_disabled_response,
)

from qc_tool.frontend.dashboard.views.api_access.shared import (
    API_JSON_MAX_BODY_BYTES,
    _api_object_permission_denied,
    _json_request_error_response,
)

logger = logging.getLogger(__name__)


def api_submit_delivery_to_eea(request):
    if not settings.SUBMISSION_ENABLED:
        return _submission_disabled_response()
    try:
        body_json = read_json_object(
            request,
            maximum_bytes=API_JSON_MAX_BODY_BYTES,
        )
        delivery_id = positive_identifier(
            body_json.get("delivery_id"),
            "delivery_id",
        )
    except JsonRequestError as exc:
        return _json_request_error_response(exc)
    except JobRequestError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    try:
        d = models.Delivery.objects.get(id=delivery_id)
    except ObjectDoesNotExist:
        response = JsonResponse({"status": "error",
                                 "message": "Delivery id={0} cannot be found in the database.".format(delivery_id)})
        response.status_code = 404
        return response
    if not request.api_access.can_manage_user(d.user_id):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot modify this delivery.",
            },
            status=403,
        )
    try:
        logger.debug("delivery_submit_eea id=" + str(delivery_id))

        job = d.get_submittable_job()
        if job is None:
            message = "Delivery with ID '{:d}' cannot be submitted to EEA. Status is not OK.)".format(d.id)
            response = JsonResponse({"status": "error", "message": message})
            response.status_code = 400
            return response
        submission_date = timezone.now()

        # check if the delivery is from local or S3 storage
        if d.s3:
            submit_job(job.job_uuid, None, CONFIG["submission_dir"], submission_date, is_s3=True)
        else:
            zip_filepath = resolve_user_delivery_upload(
                d.filename,
                media_root=settings.MEDIA_ROOT,
                username=d.user.username,
            )
            submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)
        d.submit()
        d.submission_date = submission_date
        d.save()

    except DeliveryUploadPathError as exc:
        d.date_submitted = None
        d.save()
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    except Exception:
        d.date_submitted = None
        d.save()
        logger.exception(
            "Failed to submit delivery id=%s through the API.",
            d.id,
        )
        return JsonResponse(
            {
                "status": "error",
                "code": "submission_failed",
                "message": "The delivery could not be submitted.",
            },
            status=500,
        )

    return JsonResponse({"status": "ok",
                         "message": "Delivery with ID {:d} successfully submitted to EEA.".format(d.id)})
