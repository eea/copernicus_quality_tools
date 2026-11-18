"""Deployment policy that approves an uncontested published submission."""

from types import SimpleNamespace

from django.conf import settings

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent

from .errors import SubmissionError
from .review import require_approvable_product
from .review_history import record_review_decision


AUTOMATIC_REVIEWER_USERNAME = "QC Tool (automatic)"
AUTOMATIC_APPROVAL_NOTES = (
    "Approved automatically after successful QC and storage: no competing "
    "submission exists for this product unit (QC_TOOL_AUTO_APPROVE_SUBMISSIONS)."
)


def auto_approval_enabled():
    return bool(getattr(settings, "QC_TOOL_AUTO_APPROVE_SUBMISSIONS", False))


def approve_uncontested_submission(submission, *, conflict_id):
    """Approve a newly published pending candidate when the policy allows it.

    Called by finalization under the catalog and product unit locks. Products
    that cannot receive approvals leave the submission awaiting manual review;
    publication itself never fails because of this policy.
    """

    if not auto_approval_enabled() or conflict_id is not None:
        return False
    if (
        submission.publication_state != DeliverySubmission.PublicationState.PUBLISHED
        or submission.review_state != DeliverySubmission.ReviewState.PENDING
    ):
        return False
    try:
        require_approvable_product(submission.product_unit)
    except SubmissionError:
        return False
    record_review_decision(
        submission,
        decision=SubmissionReviewEvent.Decision.APPROVED,
        actor=SimpleNamespace(pk=None, username=AUTOMATIC_REVIEWER_USERNAME),
        notes=AUTOMATIC_APPROVAL_NOTES,
    )
    return True
