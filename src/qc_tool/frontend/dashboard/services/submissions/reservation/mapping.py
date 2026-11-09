"""Map retained submission rows to immutable reservation contracts."""

from ..contracts import ReservedSubmission
from ..errors import PublicationError


def reserved_contract(submission, *, already_existed):
    delivery = submission.delivery
    release = submission.product_release
    definition = submission.job.qc_definition
    linked_definition = definition is not None and release.definition_links.filter(
        qc_definition_id=definition.pk,
    ).exists()
    original = _original_publication_identity(submission)
    return ReservedSubmission(
        submission_uuid=submission.submission_uuid,
        delivery_id=submission.delivery_id,
        job_uuid=submission.job_id,
        product_release_id=submission.product_release_id,
        product_unit_id=submission.product_unit_id,
        release_key=release.release_key,
        product_unit_code=submission.product_unit_code,
        verified_product_unit_code=submission.verified_product_unit_code,
        username=delivery.user.username if delivery.user_id else "",
        filename=delivery.filename,
        is_s3=delivery.s3_id is not None,
        # Use the immutable reservation snapshot, not mutable job state, when
        # a failed or interrupted publication is retried.
        expected_input_digest=submission.input_digest,
        requested_at_iso=submission.requested_at.isoformat(),
        already_existed=already_existed,
        artifact_key=submission.artifact_key,
        product_id=release.product_id,
        product_ident=release.product.ident,
        release_revision=release.revision,
        definition_digest=definition.digest if linked_definition else "",
        original_publication_identity=original,
    )


def _original_publication_identity(submission):
    if submission.publication_state != "published":
        return None
    from qc_tool.database.transfers.contracts import TransferError
    from qc_tool.database.transfers.provenance import publication_identity

    try:
        return publication_identity(submission)
    except TransferError as exc:
        raise PublicationError(
            "publication_provenance_unavailable",
            "The retained publication's original identity could not be verified.", 409,
        ) from exc
