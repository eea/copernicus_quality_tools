"""Atomic database finalization after filesystem publication succeeds."""

from django.db import transaction
from django.utils import timezone

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductUnit

from ..conflicts import reconcile_published_submission
from ..errors import SubmissionError
from .results import result_from_submission
from .results import submission_result


@transaction.atomic
def finalize_publication(reserved, token, receipt, *, idempotent):
    """Commit publication, delivery projection, and duplicate review state."""

    # All delivery mutators acquire the Delivery row first.
    delivery = Delivery.objects.select_for_update().get(pk=reserved.delivery_id)
    # Review and publication serialize on the product unit before locking candidates.
    # Holding a candidate before the product unit could deadlock two publishers/reviewers.
    ProductUnit.objects.select_for_update().get(pk=reserved.product_unit_id)
    submission = (
        DeliverySubmission.objects.select_for_update()
        .select_related("product_unit")
        .get(pk=reserved.submission_uuid)
    )
    if submission.publication_state == DeliverySubmission.PublicationState.PUBLISHED:
        return result_from_submission(submission, idempotent=True)
    _require_owned_claim(submission, token)
    published_at = timezone.now()
    _apply_receipt(submission, receipt, published_at=published_at)
    _apply_delivery_projection(delivery, receipt, published_at=published_at)
    conflict_id = reconcile_published_submission(submission, published_at)
    submission.refresh_from_db(fields=("review_state",))
    return submission_result(
        submission,
        conflict_id=conflict_id,
        idempotent=idempotent,
    )


def _require_owned_claim(submission, token):
    if (
        submission.publication_state
        != DeliverySubmission.PublicationState.PUBLISHING
        or submission.publication_token != token
    ):
        raise SubmissionError(
            "submission_claim_lost",
            "The publication claim changed before it could be finalized.",
            409,
        )


def _apply_receipt(submission, receipt, *, published_at):
    submission.publication_state = DeliverySubmission.PublicationState.PUBLISHED
    submission.published_at = published_at
    submission.artifact_key = receipt.artifact_key
    submission.artifact_digest = receipt.artifact_digest
    submission.input_digest = receipt.input_digest
    submission.failure_code = ""
    submission.failure_message = ""
    submission.save(
        update_fields=(
            "publication_state",
            "published_at",
            "artifact_key",
            "artifact_digest",
            "input_digest",
            "failure_code",
            "failure_message",
        )
    )


def _apply_delivery_projection(delivery, receipt, *, published_at):
    if (
        delivery.content_sha256
        and receipt.input_digest
        and delivery.content_sha256 != receipt.input_digest
    ):
        raise SubmissionError(
            "delivery_digest_mismatch",
            "The published input checksum conflicts with delivery history.",
            409,
        )
    updates = []
    if delivery.date_submitted is None:
        delivery.date_submitted = published_at
        updates.append("date_submitted")
    if receipt.input_digest and not delivery.content_sha256:
        delivery.content_sha256 = receipt.input_digest
        updates.append("content_sha256")
    if updates:
        delivery.save(update_fields=updates)
