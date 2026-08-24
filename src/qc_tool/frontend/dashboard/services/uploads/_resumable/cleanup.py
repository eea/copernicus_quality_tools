"""Constrained rollback after publication but before database registration."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .errors import ResumableUploadError
from .filesystem import open_directory
from .paths import ResumableUploadPaths


def remove_published_upload(
    paths: ResumableUploadPaths,
    published_path: str | os.PathLike[str],
) -> bool:
    """Remove only the exact regular file published for these upload paths."""

    candidate = Path(published_path)
    if candidate != paths.target_path or candidate.parent != paths.user_root:
        raise _unsafe_cleanup()

    directory_descriptor = open_directory(paths.user_root)
    try:
        try:
            file_status = os.stat(
                candidate.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _cleanup_error() from exc
        if not stat.S_ISREG(file_status.st_mode):
            raise _unsafe_cleanup()
        try:
            os.unlink(candidate.name, dir_fd=directory_descriptor)
        except OSError as exc:
            raise _cleanup_error() from exc
        return True
    finally:
        os.close(directory_descriptor)


def _unsafe_cleanup() -> ResumableUploadError:
    return ResumableUploadError(
        "unsafe_upload_cleanup",
        "The published upload could not be cleaned up safely.",
        500,
    )


def _cleanup_error() -> ResumableUploadError:
    return ResumableUploadError(
        "upload_cleanup_error",
        "The published upload could not be cleaned up.",
        500,
    )

