"""Bind correction uploads to an owned, rejected submission and its filename."""

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.submissions.artifacts import open_submission_file

from ._resumable.errors import ResumableUploadError
from ._resumable.descriptor import correction_identifier


def require_correction_submission(submission_id, *, user, filename=None, delivery_id=None, locked=False, allow_retired=False):
    query = DeliverySubmission.objects.select_for_update() if locked else DeliverySubmission.objects
    submission = query.filter(pk=submission_id, delivery__user_id=user.pk).first()
    if submission is None:
        raise ResumableUploadError("correction_not_available", "This correction is not available.", 404)
    if filename is not None and submission.delivery.filename != filename:
        raise ResumableUploadError(
            "correction_filename_mismatch",
            "Use the original filename for this correction: {}.".format(submission.delivery.filename), 400,
        )
    if delivery_id is not None and submission.delivery_id != delivery_id:
        raise ResumableUploadError(
            "correction_target_mismatch", "The correction must replace its original delivery.", 409,
        )
    # A committed retirement must remain recoverable if a reviewer later changes
    # the archived receipt. Only the exact overwrite journal can finish it.
    recovering = allow_retired and submission.delivery.is_deleted
    if not recovering and (submission.review_state != "rejected" or submission.publication_state != "published"):
        raise ResumableUploadError(
            "correction_not_available", "Only a rejected, fully stored submission can receive a correction.", 409,
        )
    return submission


def verify_retained_correction_input(submission):
    """Confirm the archived original before replacing the working upload."""

    try:
        with open_submission_file(submission, "input.d/" + submission.delivery.filename):
            pass
    except (ArtifactUnavailable, OSError) as exc:
        raise ResumableUploadError(
            "correction_archive_unavailable",
            "The original submitted ZIP could not be verified in retained storage. Try again when storage is available.",
            503,
        ) from exc
