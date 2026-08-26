"""Orchestrate reservation, artifact publication, and database finalization."""

from django.conf import settings

from qc_tool.common import CONFIG

from .errors import PublicationError
from .errors import SubmissionError
from .publication import publish_reserved_submission
from .publication import publication_layout
from .reservation import reserve_submission as _reserve_submission
from .state import claim_publication as _claim_publication
from .state import finalize_publication as _finalize_publication
from .state import mark_publication_failed as _mark_publication_failed
from .state import published_result as _published_result


def submit_delivery(
    *,
    delivery_id,
    actor,
    account_access,
    request_channel,
    api_token=None,
    submission_root=None,
    media_root=None,
):
    """Publish one eligible delivery with durable, idempotent semantics."""

    if submission_root is None:
        submission_root = CONFIG.get("submission_dir")
    if media_root is None:
        media_root = settings.MEDIA_ROOT
    if submission_root is None:
        raise SubmissionError(
            "submission_disabled",
            "Delivery submission is not enabled.",
            503,
        )

    reserved = _reserve_submission(
        delivery_id=delivery_id,
        actor=actor,
        account_access=account_access,
        request_channel=request_channel,
        api_token=api_token,
    )
    existing_result = _published_result(
        reserved.submission_uuid,
        idempotent=True,
    )
    if existing_result is not None:
        return existing_result

    layout = publication_layout(reserved, submission_root=submission_root)
    publication_token = _claim_publication(
        reserved.submission_uuid,
        allow_recovery=(
            layout.final_directory.exists()
            or layout.final_directory.is_symlink()
        ),
    )
    if publication_token is None:
        result = _published_result(
            reserved.submission_uuid,
            idempotent=True,
        )
        if result is None:
            raise SubmissionError(
                "submission_changed",
                "The submission changed while the request was processed.",
                409,
            )
        return result

    receipt = _publish_or_record_failure(
        reserved,
        publication_token,
        submission_root=submission_root,
        media_root=media_root,
    )
    try:
        return _finalize_publication(
            reserved,
            publication_token,
            receipt,
            idempotent=(
                reserved.already_existed or receipt.recovered_existing
            ),
        )
    except SubmissionError as exc:
        _record_failure(reserved, publication_token, exc)
        raise


def _publish_or_record_failure(
    reserved,
    publication_token,
    *,
    submission_root,
    media_root,
):
    try:
        return publish_reserved_submission(
            reserved,
            submission_root=submission_root,
            media_root=media_root,
        )
    except SubmissionError as exc:
        _record_failure(reserved, publication_token, exc)
        raise
    except Exception as exc:
        error = PublicationError(
            "artifact_publication_failed",
            "The validated delivery artifacts could not be published.",
            500,
        )
        _record_failure(reserved, publication_token, error)
        raise error from exc


def _record_failure(reserved, publication_token, error):
    _mark_publication_failed(
        reserved.submission_uuid,
        publication_token,
        code=error.code,
        message=error.message,
    )
