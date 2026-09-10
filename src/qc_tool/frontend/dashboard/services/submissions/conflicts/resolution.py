"""Product-manager selection of one published duplicate-AOI candidate."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionConflictEvent
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent
from qc_tool.frontend.dashboard.services.catalog.sync.locks import lock_catalog_sync

from ..contracts import ConflictResolutionResult
from ..errors import SubmissionError
from ..review_history import record_review_decision
from .access import require_resolution_scope


def resolve_submission_conflict(
    *,
    conflict_id,
    selected_submission_id,
    actor,
    account_access,
    expected_version,
    notes="",
):
    """Select one candidate without deleting or rewriting competing history."""

    product_aoi_id = _conflict_product_aoi_id(conflict_id)
    with transaction.atomic():
        lock_catalog_sync()
        product_aoi = (
            ProductAOI.objects.select_for_update(of=("self",))
            .select_related("product_release__product")
            .get(pk=product_aoi_id)
        )
        conflict = SubmissionConflict.objects.select_for_update().get(
            pk=conflict_id
        )
        require_resolution_scope(account_access, product_aoi)
        _require_current_version(conflict, expected_version)
        selected = _published_candidate(selected_submission_id, product_aoi)
        from ..review import require_approvable_product

        require_approvable_product(product_aoi)
        notes = str(notes or "").strip()
        if len(notes) > 5_000:
            raise SubmissionError("review_notes_too_long", "Review notes must be at most 5,000 characters.", 400)
        if not notes and DeliverySubmission.objects.filter(
            product_aoi=product_aoi, review_state=DeliverySubmission.ReviewState.ACCEPTED,
        ).exclude(pk=selected.pk).exists():
            raise SubmissionError("review_reason_required", "Explain why this delivery replaces the approved submission.", 400)

        if (
            conflict.state == SubmissionConflict.State.RESOLVED
            and conflict.selected_submission_id == selected.pk
        ):
            return _resolution_result(conflict, selected)

        _apply_resolution(conflict, selected, actor=actor, notes=notes)
        _select_candidate(product_aoi, selected, actor=actor, notes=conflict.resolution_notes)
        _append_resolution_event(conflict, selected, actor=actor)
        return _resolution_result(conflict, selected)


def _conflict_product_aoi_id(conflict_id):
    try:
        return SubmissionConflict.objects.values_list(
            "product_aoi_id", flat=True
        ).get(pk=conflict_id)
    except SubmissionConflict.DoesNotExist as exc:
        raise SubmissionError(
            "submission_conflict_not_found",
            "The submission conflict does not exist.",
            404,
        ) from exc


def _require_current_version(conflict, expected_version):
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version != conflict.version
    ):
        raise SubmissionError(
            "submission_conflict_changed",
            "The conflict changed after it was loaded. Refresh and try again.",
            409,
        )


def _published_candidate(selected_submission_id, product_aoi):
    try:
        selected = DeliverySubmission.objects.select_for_update().get(
            pk=selected_submission_id
        )
    except (DeliverySubmission.DoesNotExist, ValidationError, ValueError) as exc:
        raise SubmissionError(
            "submission_candidate_not_found",
            "The selected submission candidate does not exist.",
            404,
        ) from exc
    if selected.product_aoi_id != product_aoi.pk:
        raise SubmissionError(
            "submission_candidate_mismatch",
            "The selected candidate does not belong to this AOI conflict.",
            409,
        )
    if selected.publication_state != DeliverySubmission.PublicationState.PUBLISHED:
        raise SubmissionError(
            "submission_candidate_not_published",
            "Only a published candidate can resolve a conflict.",
            409,
        )
    return selected


def _apply_resolution(conflict, selected, *, actor, notes):
    conflict.state = SubmissionConflict.State.RESOLVED
    conflict.version += 1
    conflict.selected_submission = selected
    conflict.resolved_at = timezone.now()
    conflict.resolved_by = actor if getattr(actor, "pk", None) else None
    conflict.resolved_by_username = _actor_username(actor)
    conflict.resolution_notes = str(notes or "")[:5_000]
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


def _select_candidate(product_aoi, selected, *, actor, notes):
    candidates = DeliverySubmission.objects.select_for_update().filter(
        product_aoi=product_aoi,
        publication_state=DeliverySubmission.PublicationState.PUBLISHED,
    )
    for candidate in candidates.order_by("submission_uuid"):
        approved = candidate.pk == selected.pk
        record_review_decision(
            candidate,
            decision=(SubmissionReviewEvent.Decision.APPROVED if approved else SubmissionReviewEvent.Decision.DECLINED),
            actor=actor,
            notes=(notes if approved else "Another delivery was selected for this AOI." + (" " + notes if notes else "")),
        )


def _append_resolution_event(conflict, selected, *, actor):
    SubmissionConflictEvent.objects.create(
        conflict=conflict,
        version=conflict.version,
        event_type=SubmissionConflictEvent.EventType.RESOLVED,
        actor=actor if getattr(actor, "pk", None) else None,
        actor_username=_actor_username(actor),
        selected_submission=selected,
        notes=conflict.resolution_notes,
    )


def _resolution_result(conflict, selected):
    return ConflictResolutionResult(
        conflict_id=conflict.pk,
        version=conflict.version,
        selected_submission_uuid=selected.submission_uuid,
    )


def _actor_username(actor):
    if actor is None:
        return ""
    getter = getattr(actor, "get_username", None)
    return str(getter() if callable(getter) else getattr(actor, "username", ""))[
        :150
    ]
