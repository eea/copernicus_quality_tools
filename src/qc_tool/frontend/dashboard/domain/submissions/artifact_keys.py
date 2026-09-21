"""Validation for portable publication receipt storage keys."""

from pathlib import PurePosixPath, PureWindowsPath


def validate_artifact_key(key):
    """Reject ambiguous paths before joining a receipt to local storage."""

    if (
        not isinstance(key, str)
        or not key
        or "\\" in key
        or "\x00" in key
        or PurePosixPath(key).is_absolute()
        or PureWindowsPath(key).drive
        or any(part in ("", ".", "..") for part in key.split("/"))
    ):
        raise ValueError("A retained artifact key must be a canonical relative path.")
