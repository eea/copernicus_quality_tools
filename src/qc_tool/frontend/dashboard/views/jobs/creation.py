"""Browser endpoint for creating QC jobs in an atomic batch."""

import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import (
    parse_batch_job_creation_request,
)


logger = logging.getLogger(__name__)


def create_job(request):
    """Validate and create all requested QC jobs atomically."""

    try:
        job_request = parse_batch_job_creation_request(request.POST)
    except JobRequestError as exc:
        return _error_response(exc.code, exc.message, status=400)

    deliveries = _load_deliveries(job_request.delivery_ids)
    if len(deliveries) != len(job_request.delivery_ids):
        return _error_response(
            "delivery_not_found",
            "One or more selected deliveries do not exist.",
            status=404,
        )

    account_access = access_for_request(request)
    for delivery_id in job_request.delivery_ids:
        if not account_access.can_manage_user(deliveries[delivery_id].user_id):
            raise PermissionDenied(
                "A selected delivery belongs to another user."
            )

    try:
        _create_jobs(
            job_request,
            deliveries,
            request=request,
            account_access=account_access,
        )
    except PermissionError as exc:
        return _error_response(
            "object_permission_denied",
            str(exc),
            status=403,
        )
    except ValueError as exc:
        return _error_response(
            "delivery_not_eligible_for_qc",
            str(exc),
            status=409,
        )
    except Exception:
        logger.exception("A QC job batch could not be created.")
        return _error_response(
            "job_creation_failed",
            "The QC jobs could not be created.",
            status=500,
        )

    num_created = len(job_request.delivery_ids)
    return JsonResponse(
        {
            "num_created": num_created,
            "status": "OK",
            "message": _success_message(
                num_created,
                job_request.product_ident,
            ),
        }
    )


def _load_deliveries(delivery_ids):
    return {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }


def _create_jobs(job_request, deliveries, *, request, account_access):
    with transaction.atomic():
        # A deterministic lock order avoids deadlocks between overlapping
        # browser batches. Delivery.create_job acquires each row lock.
        for delivery_id in sorted(job_request.delivery_ids):
            delivery = deliveries[delivery_id]
            delivery.create_job(
                job_request.product_ident,
                job_request.skip_steps,
                requested_by=request.user,
                request_source="browser",
                account_access=account_access,
            )
            logger.debug("Delivery %d: job has been submitted.", delivery.id)


def _success_message(num_created, product_ident):
    if num_created == 1:
        return "QC Job has been set up for execution (product: {:s}).".format(
            product_ident
        )
    return (
        "{:d} QC Jobs have been set up for execution (product: {:s}).".format(
            num_created,
            product_ident,
        )
    )


def _error_response(code, message, *, status):
    return JsonResponse(
        {"status": "error", "code": code, "message": message},
        status=status,
    )
