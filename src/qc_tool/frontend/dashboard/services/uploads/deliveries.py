"""Safe lifecycle operations for delivery files in per-user storage."""

from __future__ import annotations

import os
import stat

from .paths import DeliveryUploadPathError
from .paths import resolve_user_delivery_upload


def remove_user_delivery_upload(*, media_root, username, filename) -> bool:
    """Delete one regular delivery ZIP without following directory or file links.

    A missing file is idempotent and returns ``False``. Invalid ownership or an
    unsafe filesystem object remains an error and must not be treated as a
    successful deletion.
    """

    try:
        delivery_path = resolve_user_delivery_upload(
            filename,
            media_root=media_root,
            username=username,
        )
    except DeliveryUploadPathError as exc:
        if exc.code in {
            "uploaded_file_not_found",
            "upload_storage_unavailable",
        }:
            # Database cleanup stays idempotent when the corresponding storage
            # directory has already been removed. No filesystem path is used.
            return False
        raise

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        directory_descriptor = os.open(delivery_path.parent, flags)
    except OSError as exc:
        raise _unsafe_delete() from exc
    try:
        try:
            file_status = os.stat(
                delivery_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _unsafe_delete() from exc
        if not stat.S_ISREG(file_status.st_mode):
            raise _unsafe_delete()
        try:
            os.unlink(delivery_path.name, dir_fd=directory_descriptor)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _unsafe_delete() from exc
        return True
    finally:
        os.close(directory_descriptor)


def _unsafe_delete():
    return DeliveryUploadPathError(
        "unsafe_delivery_delete",
        "The delivery file could not be deleted safely.",
        409,
    )
