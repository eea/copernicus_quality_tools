"""Immutable service contracts and actor snapshots for reservation."""

from ..contracts import ReservedSubmission


def reserved_contract(submission, *, already_existed):
    delivery = submission.delivery
    return ReservedSubmission(
        submission_uuid=submission.submission_uuid,
        delivery_id=submission.delivery_id,
        job_uuid=submission.job_id,
        product_release_id=submission.product_release_id,
        product_unit_id=submission.product_unit_id,
        release_key=submission.product_release.release_key,
        product_unit_code=submission.product_unit_code,
        submitted_product_unit_code=submission.submitted_product_unit_code,
        username=delivery.user.username if delivery.user_id else "",
        filename=delivery.filename,
        is_s3=delivery.s3_id is not None,
        # Use the immutable reservation snapshot, not mutable job state, when
        # a failed or interrupted publication is retried.
        expected_input_digest=submission.input_digest,
        requested_at_iso=submission.requested_at.isoformat(),
        already_existed=already_existed,
        artifact_path=submission.artifact_path,
    )


def actor_username(actor):
    if actor is None:
        return ""
    getter = getattr(actor, "get_username", None)
    return str(getter() if callable(getter) else getattr(actor, "username", ""))[
        :150
    ]
