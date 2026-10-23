import errno
import logging


logger = logging.getLogger(__name__)


class ResumableUploadError(Exception):
    """A safe error that an upload endpoint may return to its caller."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def storage_failure(error: OSError, *, operation: str) -> ResumableUploadError:
    """Classify operational I/O failures without returning server paths."""
    logger.warning("Delivery upload storage failed during %s (errno=%s)", operation, error.errno,
                   exc_info=(type(error), error, error.__traceback__))
    if error.errno in {errno.ENOSPC, errno.EDQUOT}:
        return ResumableUploadError(
            "upload_storage_full", "Upload storage is full. Ask an administrator to free space, then retry.", 507,
        )
    if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
        message = "Upload storage is not writable. Ask an administrator to check storage permissions, then retry."
    elif error.errno == errno.ENOENT:
        message = "The configured upload storage mount is unavailable. Ask an administrator to check it, then retry."
    else:
        message = "Upload storage is unavailable. Ask an administrator to check server storage, then retry."
    return ResumableUploadError("upload_storage_unavailable", message, 503)

