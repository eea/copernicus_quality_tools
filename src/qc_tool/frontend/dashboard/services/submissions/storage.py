"""Portable retained-artifact keys, relative to the configured storage root."""

from pathlib import Path

from qc_tool.frontend.dashboard.domain.submissions.artifact_keys import validate_artifact_key


def artifact_directory(root, key, *, require_exists=True):
    """Resolve a key without following symlinks within submission storage."""

    validate_artifact_key(key)
    directory = Path(root)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("The retained artifact storage root is unavailable.")
    directory = directory.resolve(strict=True)
    for part in key.split("/"):
        directory /= part
        if directory.is_symlink():
            raise ValueError("Retained artifact keys cannot traverse symbolic links.")
        if directory.exists():
            if not directory.is_dir():
                raise ValueError("The retained artifact location is not a directory.")
        elif require_exists:
            raise ValueError("The retained artifact directory is unavailable.")
    return directory


def artifact_key_for_directory(directory, root):
    """Create a portable receipt key after validating its retained location."""

    root = Path(root)
    if root.is_symlink():
        raise ValueError("The retained artifact storage root is unsafe.")
    root = root.resolve(strict=True)
    key = Path(directory).relative_to(root).as_posix()
    if artifact_directory(root, key) != Path(directory):
        raise ValueError("The retained artifact location does not match its key.")
    return key
