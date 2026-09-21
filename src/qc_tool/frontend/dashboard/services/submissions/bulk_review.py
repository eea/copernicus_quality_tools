"""Atomic approval of independent, permission-scoped submission candidates."""

from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent
from qc_tool.frontend.dashboard.services.catalog.sync.locks import lock_catalog_sync

from .access import reviewable_submissions
from .conflicts.access import require_resolution_scope
from .errors import SubmissionError
from .review import _require_current_version, require_approvable_product
from .review_history import record_review_decision


MAX_BULK_APPROVALS = 30


def annotate_bulk_approval_eligibility(queryset):
    """Load queue eligibility without per-row conflict or product lookups.

    These are presentation hints until rechecked under the review locks. A
    competing candidate must be reviewed individually, even if its conflict
    projection is missing or has already been closed.
    """

    competing = DeliverySubmission.objects.filter(
        product_unit_id=OuterRef("product_unit_id"),
        publication_state=DeliverySubmission.PublicationState.PUBLISHED,
        review_state__in=(
            DeliverySubmission.ReviewState.PENDING,
            DeliverySubmission.ReviewState.CONFLICT,
            DeliverySubmission.ReviewState.ACCEPTED,
        ),
    ).exclude(pk=OuterRef("pk"))
    conflicts = SubmissionConflict.objects.filter(
        product_unit_id=OuterRef("product_unit_id"),
        state=SubmissionConflict.State.OPEN,
    )
    return queryset.select_related(
        "product_unit__product_release__product",
    ).annotate(
        _bulk_has_open_conflict=Exists(conflicts),
        _bulk_has_competing_candidate=Exists(competing),
    )


def bulk_approval_block_reason(submission):
    """Return the reason an annotated queue row needs individual attention."""

    error = _bulk_approval_error(submission)
    return error.message if error else ""


def bulk_approve_submissions(*, selections, actor, account_access, notes=""):
    """Approve every selected receipt together, or leave all unchanged.

    ``selections`` contains (submission UUID, expected review version) pairs.
    Bulk approval never chooses between competing deliveries or changes other
    submissions. The retained review event and readiness invalidation use the
    same writer as an individual review.
    """

    versions = _selection_versions(selections)
    notes = str(notes or "").strip()
    if len(notes) > 5_000:
        raise SubmissionError(
            "review_notes_too_long", "Review notes must be at most 5,000 characters.", 400,
        )

    with transaction.atomic():
        lock_catalog_sync()
        scoped = reviewable_submissions(account_access).filter(pk__in=versions)
        identities = list(scoped.values_list("pk", "product_unit_id"))
        if len(identities) != len(versions):
            raise SubmissionError(
                "bulk_selection_unavailable",
                "One or more selected submissions are unavailable or outside your review access. Refresh the queue and select again.",
                403,
            )
        unit_ids = {unit_id for _, unit_id in identities}
        if len(unit_ids) != len(identities):
            raise SubmissionError(
                "bulk_duplicate_product_unit",
                "Select only one submission per product unit. Review competing submissions individually.",
            )

        # Catalog -> product unit -> submission matches individual reviews,
        # publication, and conflict resolution. Stable ordering also keeps
        # overlapping batches from acquiring unit locks in opposing orders.
        units = list(
            ProductUnit.objects.select_for_update(of=("self",))
            .select_related("product_release__product")
            .filter(pk__in=unit_ids).order_by("pk")
        )
        for unit in units:
            require_resolution_scope(account_access, unit)
        submissions = list(
            annotate_bulk_approval_eligibility(scoped)
            .select_for_update(of=("self",)).order_by("pk")
        )
        for submission in submissions:
            _require_current_version(submission, versions[submission.pk])
            error = _bulk_approval_error(submission)
            if error:
                raise error

        for submission in submissions:
            record_review_decision(
                submission, decision=SubmissionReviewEvent.Decision.APPROVED,
                actor=actor, notes=notes,
            )
        return len(submissions)


def _bulk_approval_error(submission):
    if submission.publication_state != DeliverySubmission.PublicationState.PUBLISHED:
        return SubmissionError(
            "submission_not_published", "The delivery must finish being stored before approval.",
        )
    if (
        submission.review_state == DeliverySubmission.ReviewState.CONFLICT
        or submission._bulk_has_open_conflict
        or submission._bulk_has_competing_candidate
    ):
        return SubmissionError(
            "bulk_competing_submissions", "Review competing submissions individually.",
        )
    if submission.review_state != DeliverySubmission.ReviewState.PENDING:
        return SubmissionError(
            "submission_already_reviewed", "This submission has already been reviewed. Refresh to see the decision.",
        )
    try:
        require_approvable_product(submission.product_unit)
    except SubmissionError as error:
        return error
    return None


def _selection_versions(selections):
    if not isinstance(selections, (list, tuple)) or not selections:
        raise SubmissionError("bulk_selection_required", "Select at least one submission to approve.", 400)
    if len(selections) > MAX_BULK_APPROVALS:
        raise SubmissionError(
            "bulk_selection_limit", f"Select at most {MAX_BULK_APPROVALS} submissions at a time.", 400,
        )
    versions = {}
    for selection in selections:
        if not isinstance(selection, (list, tuple)) or len(selection) != 2:
            raise SubmissionError("bulk_selection_invalid", "The submission selection is invalid. Refresh and select again.", 400)
        submission_id, version = selection
        try:
            if not isinstance(submission_id, (str, UUID)):
                raise ValueError
            submission_id = UUID(str(submission_id))
        except (ValueError, AttributeError) as error:
            raise SubmissionError(
                "bulk_selection_invalid", "The submission selection is invalid. Refresh and select again.", 400,
            ) from error
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise SubmissionError("bulk_version_invalid", "The submission version is invalid. Refresh and select again.", 400)
        if submission_id in versions:
            raise SubmissionError("bulk_selection_duplicate", "Each submission can be selected only once.", 400)
        versions[submission_id] = version
    return versions
