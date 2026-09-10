"""Browser adapters for the delivery-submission lifecycle service."""

import logging

from django.conf import settings
from django.http import JsonResponse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import (
    parse_positive_identifier_list,
)
from qc_tool.frontend.dashboard.services.submissions import SubmissionError


logger = logging.getLogger(__name__)


def submit_delivery_to_eea(request):
    """Submit one delivery through the shared lifecycle service."""

    if not settings.SUBMISSION_ENABLED:
        return _submission_disabled_response()
    try:
        delivery_id = parse_positive_identifier_list(
            request.POST.get("id"),
            maximum_items=1,
        )[0]
    except IdentifierListError as exc:
        return _submission_error_response(exc, status=400)

    try:
        result = _submit_delivery(
            delivery_id=delivery_id,
            actor=request.user,
            account_access=access_for_request(request),
            request_channel=models.DeliverySubmission.RequestChannel.BROWSER,
        )
    except SubmissionError as exc:
        return _submission_error_response(exc, status=exc.status_code)
    except Exception:
        logger.exception("Failed to submit delivery id=%s.", delivery_id)
        return _unexpected_submission_error()

    return JsonResponse(
        {
            "status": "ok",
            "message": "Delivery {} successfully submitted for review.".format(
                delivery_id
            ),
            "data": result.as_dict(),
        }
    )


def submit_deliveries_to_eea_batch(request):
    """Submit multiple deliveries and report per-delivery failures."""

    if not settings.SUBMISSION_ENABLED:
        return _submission_disabled_response()
    try:
        delivery_ids = parse_positive_identifier_list(request.POST.get("ids"))
    except IdentifierListError as exc:
        return _submission_error_response(exc, status=400)

    submitted_results, failed_details = _submit_batch(
        delivery_ids,
        request=request,
    )
    if not submitted_results:
        return JsonResponse(
            {
                "status": "error",
                "message": "None of the deliveries could be submitted.",
                "details": failed_details,
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "ok",
            "message": "{}/{} deliveries successfully submitted.".format(
                len(submitted_results),
                len(delivery_ids),
            ),
            "data": [result.as_dict() for result in submitted_results],
            "failed": failed_details,
        }
    )


def _submit_batch(delivery_ids, *, request):
    submitted_results = []
    failed_details = []
    account_access = access_for_request(request)

    for delivery_id in delivery_ids:
        try:
            result = _submit_delivery(
                delivery_id=delivery_id,
                actor=request.user,
                account_access=account_access,
                request_channel=(
                    models.DeliverySubmission.RequestChannel.BROWSER
                ),
            )
            submitted_results.append(result)
        except SubmissionError as exc:
            failed_details.append(
                _failure_detail(delivery_id, exc.code, exc.message)
            )
        except Exception:
            logger.exception("Failed to submit delivery id=%s.", delivery_id)
            failed_details.append(
                _failure_detail(
                    delivery_id,
                    "submission_failed",
                    "The delivery could not be submitted.",
                )
            )
    return submitted_results, failed_details


def _submit_delivery(**kwargs):
    """Call the compatibility seam so legacy patch targets keep working."""

    from qc_tool.frontend.dashboard.views.deliveries import actions

    return actions.submit_delivery(**kwargs)


def _failure_detail(delivery_id, code, message):
    return {
        "delivery_id": delivery_id,
        "code": code,
        "message": message,
    }


def _submission_error_response(exc, *, status):
    return JsonResponse(
        {"status": "error", "code": exc.code, "message": exc.message},
        status=status,
    )


def _unexpected_submission_error():
    return JsonResponse(
        {
            "status": "error",
            "code": "submission_failed",
            "message": "The delivery could not be submitted.",
        },
        status=500,
    )


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
