"""Flag competing deliveries without invalidating an existing approval."""

from django.db.models import F

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
        .exclude(review_state=DeliverySubmission.ReviewState.REJECTED)
        .select_related("delivery")
        .order_by("requested_at", "submission_uuid")
    )
    if len(candidates) < 2:
        return None

    conflict = (
        SubmissionConflict.objects.select_for_update()
        .filter(product_aoi_id=submission.product_aoi_id)
        .first()
    )
    if conflict is None:
        conflict = _open_conflict(submission.product_aoi_id, now)
    elif conflict.state != SubmissionConflict.State.OPEN:
        _reopen_conflict(conflict)
    else:
        conflict.version += 1
        conflict.save(update_fields=("version", "updated_at"))
        _create_event(conflict, SubmissionConflictEvent.EventType.CANDIDATE_ADDED)

    DeliverySubmission.objects.filter(
        pk__in=[candidate.pk for candidate in candidates]
    ).filter(review_state__in=(
        DeliverySubmission.ReviewState.PENDING,
        DeliverySubmission.ReviewState.CONFLICT,
    )).update(
        review_state=DeliverySubmission.ReviewState.CONFLICT,
        review_version=F("review_version") + 1,
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
