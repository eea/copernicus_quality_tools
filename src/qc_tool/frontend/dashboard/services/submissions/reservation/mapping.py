"""Immutable service contracts and actor snapshots for reservation."""

from ..contracts import ReservedSubmission


def reserved_contract(submission, *, already_existed):
    delivery = submission.delivery
    return ReservedSubmission(
        submission_uuid=submission.submission_uuid,
        delivery_id=submission.delivery_id,
        job_uuid=submission.job_id,
        product_release_id=submission.product_release_id,
        product_aoi_id=submission.product_aoi_id,
        release_key=submission.product_release.release_key,
        aoi_code=submission.aoi_code,
        aoi_code_submitted=submission.aoi_code_submitted,
        username=delivery.user.username if delivery.user_id else "",
        filename=delivery.filename,
        is_s3=delivery.s3_id is not None,
        # Use the immutable reservation snapshot, not mutable job state, when
        # a failed or interrupted publication is retried.
        expected_input_digest=submission.input_digest,
        requested_at_iso=submission.requested_at.isoformat(),
        already_existed=already_existed,
    )


def actor_username(actor):
    if actor is None:
        return ""
    getter = getattr(actor, "get_username", None)
    return str(getter() if callable(getter) else getattr(actor, "username", ""))[
        :150
    ]
