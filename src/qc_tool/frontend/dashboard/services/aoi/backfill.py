"""Bounded, idempotent historical AOI metadata backfill.

Filesystem result documents cannot be read safely from a schema migration.
Operators may run the accompanying management command after deployment; live
jobs continue to populate AOI metadata through the normal status lifecycle.
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q

from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING

from .artifacts import load_aoi_result_document
from .contracts import AoiUpdateAction
from .errors import AoiResultUnavailable
from .projections import sync_locked_delivery_from_latest_job
from .results import aoi_update_from_result


@dataclass(frozen=True)
class AoiBackfillResult:
    scanned_jobs: int = 0
    candidate_jobs: int = 0
    updated_jobs: int = 0
    projected_deliveries: int = 0
    unreadable_results: int = 0
    unavailable_metadata: int = 0


def backfill_aoi_metadata(*, batch_size=100, limit=None, dry_run=False):
    """Populate missing Job AOIs from existing result documents.

    Work is ordered, bounded, and safe to repeat. Only terminal jobs with a
    currently null AOI are considered. A malformed, missing, or explicit-null
    value is left unavailable rather than guessed from a filename.
    """

    from qc_tool.frontend.dashboard.models import Delivery
    from qc_tool.frontend.dashboard.models import Job

    _validate_bounds(batch_size, limit)
    queryset = (
        Job.objects.exclude(job_status__in=(JOB_WAITING, JOB_RUNNING))
        .filter(
            Q(aoi_code_submitted__isnull=True)
            | Q(aoi_code_submitted="")
        )
        .only("job_uuid", "delivery_id")
        .order_by("date_created", "job_uuid")
    )
    if limit is not None:
        queryset = queryset[:limit]

    scanned = candidates = updated = projected = unreadable = unavailable = 0
    pending_updates = []
    for job in queryset.iterator(chunk_size=batch_size):
        scanned += 1
        try:
            result = load_aoi_result_document(job.job_uuid)
        except AoiResultUnavailable:
            unreadable += 1
            continue
        update = aoi_update_from_result(result)
        if update.action is not AoiUpdateAction.SET:
            unavailable += 1
            continue
        candidates += 1
        pending_updates.append((job.pk, job.delivery_id, update.value))

        if len(pending_updates) >= batch_size:
            count, projected_count = _apply_batch(
                Job,
                Delivery,
                pending_updates,
                dry_run=dry_run,
            )
            updated += count
            projected += projected_count
            pending_updates = []

    if pending_updates:
        count, projected_count = _apply_batch(
            Job,
            Delivery,
            pending_updates,
            dry_run=dry_run,
        )
        updated += count
        projected += projected_count

    return AoiBackfillResult(
        scanned_jobs=scanned,
        candidate_jobs=candidates,
        updated_jobs=updated,
        projected_deliveries=projected,
        unreadable_results=unreadable,
        unavailable_metadata=unavailable,
    )


def _apply_batch(Job, Delivery, updates, *, dry_run):
    if dry_run:
        return 0, 0

    updated = 0
    projected = 0
    delivery_ids = sorted({delivery_id for _, delivery_id, _ in updates})
    with transaction.atomic():
        # Use the same lock order as live creation, status, and deletion:
        # Delivery primary key first, then Job. Each bounded batch commits its
        # Job metadata and Delivery projection together, so interruption can
        # never strand a non-null Job behind a stale Delivery projection.
        deliveries = {
            delivery.pk: delivery
            for delivery in Delivery.objects.select_for_update()
            .filter(pk__in=delivery_ids)
            .order_by("pk")
        }
        changed_delivery_ids = set()
        for job_id, delivery_id, value in updates:
            changed = Job.objects.filter(
                Q(aoi_code_submitted__isnull=True)
                | Q(aoi_code_submitted=""),
                pk=job_id,
            ).update(aoi_code=value, aoi_code_submitted=value)
            if changed:
                updated += 1
                changed_delivery_ids.add(delivery_id)
        for delivery_id in sorted(changed_delivery_ids):
            delivery = deliveries.get(delivery_id)
            if delivery is None:
                continue
            sync_locked_delivery_from_latest_job(delivery)
            projected += 1
    return updated, projected


def _validate_bounds(batch_size, limit):
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 1_000:
        raise ValueError("batch_size must be between 1 and 1000")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError("limit must be a positive integer")
