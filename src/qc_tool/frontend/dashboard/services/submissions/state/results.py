"""Stable submission result projections for adapters and retries."""

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import SubmissionConflict

from ..contracts import SubmissionResult


def published_result(submission_uuid, *, idempotent):
    submission = (
        DeliverySubmission.objects.select_related("product_unit")
        .filter(
            pk=submission_uuid,
            publication_state=DeliverySubmission.PublicationState.PUBLISHED,
        )
        .first()
    )
    if submission is None:
        return None
    return result_from_submission(submission, idempotent=idempotent)


def result_from_submission(submission, *, idempotent):
    conflict_id = (
        SubmissionConflict.objects.filter(
            product_unit_id=submission.product_unit_id
        )
        .values_list("pk", flat=True)
        .first()
    )
    return submission_result(
        submission,
        conflict_id=conflict_id,
        idempotent=idempotent,
    )


def submission_result(submission, *, conflict_id, idempotent):
    return SubmissionResult(
        submission_uuid=submission.submission_uuid,
        delivery_id=submission.delivery_id,
        publication_state=submission.publication_state,
        review_state=submission.review_state,
        conflict_id=conflict_id,
        artifact_path=submission.artifact_path,
        published_at=submission.published_at,
        idempotent=idempotent,
    )
