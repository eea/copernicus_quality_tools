"""Review feedback and correction guidance shared by submission workspaces."""

from django.urls import reverse

from qc_tool.frontend.dashboard.access.deliveries import delivery_product_scope_matches
from qc_tool.frontend.dashboard.models import DeliverySubmission, SubmissionReviewEvent


def current_review_feedback(submission, *, events=None):
    """Use the event behind the current decision, never an unrelated old note."""

    decision = {
        DeliverySubmission.ReviewState.ACCEPTED: SubmissionReviewEvent.Decision.APPROVED,
        DeliverySubmission.ReviewState.REJECTED: SubmissionReviewEvent.Decision.DECLINED,
    }.get(submission.review_state)
    if decision is None:
        return None
    if events is not None:
        return next((event for event in reversed(events) if (
            event.version == submission.review_version and event.decision == decision
        )), None)
    return submission.review_events.filter(
        version=submission.review_version, decision=decision,
    ).first()


def correction_context(submission, account_access, *, events=None):
    """Only the uploader can start a correction from a rejected receipt."""

    if not (
        account_access.is_authenticated and account_access.can_upload
        and account_access.user_id == submission.delivery.user_id
        and delivery_product_scope_matches(account_access, submission.delivery)
        and submission.review_state == DeliverySubmission.ReviewState.REJECTED
        and submission.publication_state == DeliverySubmission.PublicationState.PUBLISHED
        and not submission.delivery.is_deleted
    ):
        return None
    return {
        "submission": submission,
        "feedback": current_review_feedback(submission, events=events),
        "review_url": reverse("submission_review", args=(submission.pk,)),
        "upload_url": "{}?correction_for={}".format(reverse("file_upload"), submission.pk),
    }
