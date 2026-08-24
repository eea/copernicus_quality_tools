"""Resolve API-supplied delivery paths without crossing a user's storage root."""

from __future__ import annotations

import os
from pathlib import Path
import stat


class DeliveryUploadPathError(Exception):
    """A safe, structured error raised for an invalid incoming-file reference."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def resolve_user_delivery_upload(
    supplied_path: object,
    *,
    media_root: str | os.PathLike[str],
    username: str,
) -> Path:
    """Return a regular ZIP directly below this user's incoming directory.

    The API historically accepts either a full server path or a filename. Both
    forms are retained, but subdirectories, symlinks, and paths belonging to a
    different user are rejected before any metadata is registered.
    """

    if not isinstance(supplied_path, str) or not supplied_path.strip():
        raise DeliveryUploadPathError(
            "missing_uploaded_file",
            "The uploaded_file parameter is required.",
            400,
        )
    if "\x00" in supplied_path:
        raise DeliveryUploadPathError(
            "invalid_uploaded_file",
            "The uploaded_file path is invalid.",
            400,
        )

    if (
        not isinstance(username, str)
        or not username
        or Path(username).name != username
        or username in {".", ".."}
        or "\\" in username
        or "\x00" in username
    ):
        raise DeliveryUploadPathError(
            "invalid_upload_owner",
            "The authenticated upload owner is invalid.",
            403,
        )

    try:
        storage_root = Path(media_root).resolve(strict=True)
        unresolved_user_root = storage_root / username
        if unresolved_user_root.is_symlink():
            raise DeliveryUploadPathError(
                "unsafe_upload_storage",
                "The user upload directory is not safe.",
                409,
            )
        user_root = unresolved_user_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DeliveryUploadPathError(
            "upload_storage_unavailable",
            "The user upload directory is unavailable.",
            409,
        ) from exc
    if user_root.parent != storage_root or user_root.name != username:
        raise DeliveryUploadPathError(
            "unsafe_upload_storage",
            "The user upload directory is not safe.",
            409,
        )

    requested = Path(supplied_path)
    if requested.is_absolute():
        candidate = requested
    else:
        if requested.name != supplied_path or "\\" in supplied_path:
            raise DeliveryUploadPathError(
                "uploaded_file_outside_user_storage",
                "The delivery file must belong to the authenticated user's upload directory.",
                403,
            )
        candidate = user_root / requested
    if candidate.is_symlink():
        raise DeliveryUploadPathError(
            "unsafe_uploaded_file",
            "Symbolic links cannot be registered as delivery files.",
            400,
        )

    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        raise DeliveryUploadPathError(
            "uploaded_file_not_found",
            "The uploaded delivery file does not exist.",
            404,
        ) from None
    except (OSError, RuntimeError) as exc:
        raise DeliveryUploadPathError(
            "invalid_uploaded_file",
            "The uploaded_file path is invalid.",
            400,
        ) from exc

    if resolved.parent != user_root:
        raise DeliveryUploadPathError(
            "uploaded_file_outside_user_storage",
            "The delivery file must belong to the authenticated user's upload directory.",
            403,
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(resolved, flags)
        file_status = os.fstat(descriptor)
    except OSError as exc:
        raise DeliveryUploadPathError(
            "unsafe_uploaded_file",
            "The uploaded delivery file cannot be opened safely.",
            400,
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not stat.S_ISREG(file_status.st_mode):
        raise DeliveryUploadPathError(
            "invalid_uploaded_file",
            "The uploaded_file path must refer to a regular file.",
            400,
        )
    if resolved.suffix.lower() != ".zip":
        raise DeliveryUploadPathError(
            "invalid_delivery_file_type",
            "The uploaded delivery file must use the .zip extension.",
            400,
        )

    return resolved
