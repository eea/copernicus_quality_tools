"""API delivery submission endpoints."""

import logging
from django.conf import settings
from django.http import JsonResponse
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import positive_identifier
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.submissions import submit_delivery
from qc_tool.frontend.dashboard.views.deliveries.actions.submissions import (
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
        result = submit_delivery(
            delivery_id=delivery_id,
            actor=request.api_user,
            account_access=request.api_access,
            request_channel=models.DeliverySubmission.RequestChannel.API,
            api_token=request.api_token,
        )
    except SubmissionError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    except Exception:
        logger.exception(
            "Failed to submit delivery id=%s through the API.",
            delivery_id,
        )
        return JsonResponse(
            {
                "status": "error",
                "code": "submission_failed",
                "message": "The delivery could not be submitted.",
            },
            status=500,
        )

    return JsonResponse(
        {
            "status": "ok",
            "message": (
                "Delivery with ID {:d} successfully submitted to EEA.".format(
                    delivery_id
                )
            ),
            "data": result.as_dict(),
        }
    )
