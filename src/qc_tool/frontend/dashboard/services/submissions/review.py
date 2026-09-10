"""Scoped, version-checked decisions for submitted deliveries."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionConflictEvent
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent
from qc_tool.frontend.dashboard.services.catalog.sync.locks import lock_catalog_sync

from .conflicts.access import require_resolution_scope
from .errors import SubmissionError
from .review_history import record_review_decision
from .reservation.mapping import actor_username


def review_submission(
    *, submission_id, decision, actor, account_access,
    expected_review_version, notes="",
):
    """Approve or decline a safely published candidate; retain every receipt."""

    if decision not in SubmissionReviewEvent.Decision.values:
        raise SubmissionError("invalid_review_decision", "Choose approve or decline.", 400)
    notes = str(notes or "").strip()
    if len(notes) > 5_000:
        raise SubmissionError("review_notes_too_long", "Review notes must be at most 5,000 characters.", 400)
    if decision == SubmissionReviewEvent.Decision.DECLINED and not notes:
        raise SubmissionError("review_reason_required", "Explain why this delivery is declined.", 400)
    try:
        aoi_id = DeliverySubmission.objects.values_list("product_aoi_id", flat=True).get(pk=submission_id)
    except (DeliverySubmission.DoesNotExist, ValidationError, ValueError) as exc:
        raise SubmissionError("submission_not_found", "The submission does not exist.", 404) from exc

    with transaction.atomic():
        lock_catalog_sync()
        product_aoi = (
            ProductAOI.objects.select_for_update(of=("self",))
            .select_related("product_release__product").get(pk=aoi_id)
        )
        require_resolution_scope(account_access, product_aoi)
        submission = DeliverySubmission.objects.select_for_update().get(pk=submission_id)
        _require_current_version(submission, expected_review_version)
        if submission.publication_state != DeliverySubmission.PublicationState.PUBLISHED:
            raise SubmissionError("submission_not_published", "The delivery must finish being stored before it can be reviewed.")
        if submission.review_state not in (
            DeliverySubmission.ReviewState.PENDING, DeliverySubmission.ReviewState.CONFLICT,
        ):
            raise SubmissionError("submission_already_reviewed", "This submission has already been reviewed. Refresh to see the decision.")
        if decision == SubmissionReviewEvent.Decision.APPROVED:
            require_approvable_product(product_aoi)
            competing_approval = DeliverySubmission.objects.filter(
                product_aoi=product_aoi,
                publication_state=DeliverySubmission.PublicationState.PUBLISHED,
                review_state=DeliverySubmission.ReviewState.ACCEPTED,
            ).exclude(pk=submission.pk).exists()
            if competing_approval:
                raise SubmissionError(
                    "approved_candidate_exists",
                    "A delivery is already approved for this AOI. Resolve the competing submissions to replace it.",
                )
            conflict = SubmissionConflict.objects.filter(product_aoi=product_aoi).first()
            if conflict is not None:
                from .conflicts.resolution import resolve_submission_conflict

                resolve_submission_conflict(
                    conflict_id=conflict.pk, selected_submission_id=submission.pk,
                    actor=actor, account_access=account_access,
                    expected_version=conflict.version, notes=notes,
                )
                submission.refresh_from_db()
                return submission
        record_review_decision(submission, decision=decision, actor=actor, notes=notes)
        _close_reviewed_conflict(product_aoi, actor=actor)
        return submission


def require_approvable_product(product_aoi):
    release = product_aoi.product_release
    if not release.product.is_active:
        raise SubmissionError("product_archived", "An archived product cannot receive new approvals.")
    if release.coverage_state != ProductRelease.CoverageState.AUTHORITATIVE:
        raise SubmissionError("delivery_plan_not_active", "Activate the delivery plan before approving submissions.")


def _require_current_version(submission, expected_version):
    if (
        isinstance(expected_version, bool) or not isinstance(expected_version, int)
        or expected_version != submission.review_version
    ):
        raise SubmissionError(
            "submission_review_changed",
            "The submission changed after it was loaded. Refresh and try again.",
        )


def _close_reviewed_conflict(product_aoi, *, actor):
    conflict = SubmissionConflict.objects.select_for_update().filter(
        product_aoi=product_aoi, state=SubmissionConflict.State.OPEN,
    ).first()
    if conflict is None:
        return
    candidates = DeliverySubmission.objects.filter(
        product_aoi=product_aoi,
        publication_state=DeliverySubmission.PublicationState.PUBLISHED,
    )
    if candidates.filter(review_state__in=(
        DeliverySubmission.ReviewState.PENDING, DeliverySubmission.ReviewState.CONFLICT,
    )).exists():
        candidates.filter(review_state__in=(
            DeliverySubmission.ReviewState.PENDING, DeliverySubmission.ReviewState.CONFLICT,
        )).update(review_version=F("review_version") + 1)
        conflict.version += 1
        conflict.save(update_fields=("version", "updated_at"))
        return
    selected = candidates.filter(review_state=DeliverySubmission.ReviewState.ACCEPTED).first()
    conflict.state = SubmissionConflict.State.RESOLVED if selected else SubmissionConflict.State.DISMISSED
    conflict.version += 1
    conflict.selected_submission = selected
    conflict.resolved_at = timezone.now()
    conflict.resolved_by = actor if getattr(actor, "pk", None) else None
    conflict.resolved_by_username = actor_username(actor)
    conflict.resolution_notes = "All candidate reviews completed."
    conflict.save(update_fields=(
        "state", "version", "selected_submission", "resolved_at", "resolved_by",
        "resolved_by_username", "resolution_notes", "updated_at",
    ))
    SubmissionConflictEvent.objects.create(
        conflict=conflict, version=conflict.version,
        event_type=(SubmissionConflictEvent.EventType.RESOLVED if selected else SubmissionConflictEvent.EventType.DISMISSED),
        selected_submission=selected, actor=conflict.resolved_by,
        actor_username=conflict.resolved_by_username, notes=conflict.resolution_notes,
    )
