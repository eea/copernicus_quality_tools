"""Open or reopen review when distinct users publish the same expected AOI."""

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionConflictEvent


def reconcile_published_submission(submission, now):
    """Create current conflict state while retaining every candidate."""

    candidates = list(
        DeliverySubmission.objects.filter(
            product_aoi_id=submission.product_aoi_id,
            publication_state=DeliverySubmission.PublicationState.PUBLISHED,
        )
        .select_related("delivery")
        .order_by("requested_at", "submission_uuid")
    )
    owner_ids = {
        candidate.delivery.user_id
        for candidate in candidates
        if candidate.delivery.user_id is not None
    }
    if len(owner_ids) < 2:
        return None

    conflict = (
        SubmissionConflict.objects.select_for_update()
        .filter(product_aoi_id=submission.product_aoi_id)
        .first()
    )
    if conflict is None:
        conflict = _open_conflict(submission.product_aoi_id, now)
    elif conflict.state == SubmissionConflict.State.RESOLVED:
        _reopen_conflict(conflict)

    DeliverySubmission.objects.filter(
        pk__in=[candidate.pk for candidate in candidates]
    ).exclude(review_state=DeliverySubmission.ReviewState.CONFLICT).update(
        review_state=DeliverySubmission.ReviewState.CONFLICT
    )
    return conflict.pk


def _open_conflict(product_aoi_id, now):
    conflict = SubmissionConflict.objects.create(
        product_aoi_id=product_aoi_id,
        state=SubmissionConflict.State.OPEN,
        version=1,
        opened_at=now,
    )
    _create_event(conflict, SubmissionConflictEvent.EventType.OPENED)
    return conflict


def _reopen_conflict(conflict):
    conflict.state = SubmissionConflict.State.OPEN
    conflict.version += 1
    conflict.selected_submission = None
    conflict.resolved_at = None
    conflict.resolved_by = None
    conflict.resolved_by_username = ""
    conflict.resolution_notes = ""
    conflict.save(
        update_fields=(
            "state",
            "version",
            "selected_submission",
            "resolved_at",
            "resolved_by",
            "resolved_by_username",
            "resolution_notes",
            "updated_at",
        )
    )
    _create_event(conflict, SubmissionConflictEvent.EventType.REOPENED)


def _create_event(conflict, event_type):
    SubmissionConflictEvent.objects.create(
        conflict=conflict,
        version=conflict.version,
        event_type=event_type,
    )
