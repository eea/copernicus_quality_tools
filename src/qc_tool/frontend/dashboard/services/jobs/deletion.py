"""Transactional job-history deletion with delivery reprojection."""

from dataclasses import dataclass

from django.db import transaction

from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.aoi.projections import (
    sync_locked_delivery_from_latest_job,
)


@dataclass(frozen=True)
class JobDeletionError(Exception):
    code: str
    message: str
    status_code: int


def delete_jobs_and_reproject(job_uuids, account_access):
    """Delete an authorized job set and refresh each delivery projection.

    Every mutator uses the same lock order: Delivery primary key first, then
    Job UUID. This makes overlapping batches deterministic and keeps object
    authorization inside the transaction that performs the deletion.
    """

    expected_count = len(job_uuids)
    candidate_delivery_ids = list(
        Job.objects.filter(job_uuid__in=job_uuids)
        .values_list("delivery_id", flat=True)
        .distinct()
    )
    if not candidate_delivery_ids:
        raise _not_found()

    with transaction.atomic():
        deliveries = {
            delivery.pk: delivery
            for delivery in Delivery.objects.select_for_update()
            .filter(pk__in=candidate_delivery_ids)
            .order_by("pk")
        }
        jobs = list(
            Job.objects.select_for_update()
            .filter(job_uuid__in=job_uuids)
            .select_related("delivery")
            .order_by("job_uuid")
        )
        if len(jobs) != expected_count:
            raise _not_found()
        if any(job.delivery_id not in deliveries for job in jobs):
            raise JobDeletionError(
                "job_changed",
                "A selected job changed while the request was processed. "
                "Refresh and try again.",
                409,
            )
        if any(
            not account_access.can_manage_user(job.delivery.user_id)
            for job in jobs
        ):
            raise JobDeletionError(
                "object_permission_denied",
                "The account cannot delete one or more selected jobs.",
                403,
            )
        if any(job.job_status == JOB_RUNNING for job in jobs):
            raise JobDeletionError(
                "job_is_running",
                "A running QC job cannot be deleted.",
                409,
            )

        deleted_count, _details = Job.objects.filter(
            job_uuid__in=job_uuids
        ).delete()
        for delivery in deliveries.values():
            sync_locked_delivery_from_latest_job(delivery)
    return deleted_count


def _not_found():
    return JobDeletionError(
        "job_not_found",
        "One or more selected jobs do not exist.",
        404,
    )
