"""Exclusive, retryable publication claim transitions."""

from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from qc_tool.frontend.dashboard.models import DeliverySubmission

from ..errors import SubmissionError


PUBLICATION_CLAIM_TIMEOUT = timedelta(minutes=15)


@transaction.atomic
def claim_publication(submission_uuid, *, allow_recovery=False):
    """Claim publication work, or report an idempotent completion."""

    submission = DeliverySubmission.objects.select_for_update().get(
        pk=submission_uuid
    )
    if submission.publication_state == DeliverySubmission.PublicationState.PUBLISHED:
        return None
    now = timezone.now()
    if _has_live_claim(submission, now) and not allow_recovery:
        raise SubmissionError(
            "submission_in_progress",
            "This delivery is already being published.",
            409,
        )

    token = uuid4()
    submission.publication_state = DeliverySubmission.PublicationState.PUBLISHING
    submission.publication_claimed_at = now
    submission.publication_token = token
    submission.failure_code = ""
    submission.failure_message = ""
    submission.save(
        update_fields=(
            "publication_state",
            "publication_claimed_at",
            "publication_token",
            "failure_code",
            "failure_message",
        )
    )
    return token


def _has_live_claim(submission, now):
    return bool(
        submission.publication_state
        == DeliverySubmission.PublicationState.PUBLISHING
        and submission.publication_claimed_at is not None
        and submission.publication_claimed_at
        > now - PUBLICATION_CLAIM_TIMEOUT
    )


@transaction.atomic
def mark_publication_failed(submission_uuid, token, *, code, message):
    """Record failure only when the caller still owns the claim."""

    submission = DeliverySubmission.objects.select_for_update().get(
        pk=submission_uuid
    )
    if submission.publication_state == DeliverySubmission.PublicationState.PUBLISHED:
        return
    if submission.publication_token != token:
        return
    submission.publication_state = DeliverySubmission.PublicationState.FAILED
    submission.failure_code = str(code)[:64]
    submission.failure_message = str(message)[:500]
    submission.save(
        update_fields=(
            "publication_state",
            "failure_code",
            "failure_message",
        )
    )
