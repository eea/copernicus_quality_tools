"""Apply a reviewed projection and retain the corresponding decision together."""

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent

from .reservation.mapping import actor_username


def record_review_decision(submission, *, decision, actor, notes):
    """Called under the product unit lock and transaction by review application services."""

    state = (
        DeliverySubmission.ReviewState.ACCEPTED
        if decision == SubmissionReviewEvent.Decision.APPROVED
        else DeliverySubmission.ReviewState.REJECTED
    )
    if submission.review_state == state:
        return
    previous_state = submission.review_state
    submission.review_state = state
    submission.review_version += 1
    submission.save(update_fields=("review_state", "review_version"))
    SubmissionReviewEvent.objects.create(
        submission=submission, version=submission.review_version,
        decision=decision, actor=actor if getattr(actor, "pk", None) else None,
        actor_username=actor_username(actor), notes=notes,
    )
    if DeliverySubmission.ReviewState.ACCEPTED in (previous_state, state):
        from qc_tool.frontend.dashboard.services.catalog.readiness import invalidate_product_readiness

        product_id = ProductRelease.objects.filter(
            pk=submission.product_release_id, is_current=True,
        ).values_list("product_id", flat=True).first()
        if product_id is not None:
            invalidate_product_readiness(product_id)
