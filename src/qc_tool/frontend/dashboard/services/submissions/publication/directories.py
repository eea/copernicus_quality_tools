"""No-follow publication directories and submission-owned staging cleanup."""

from pathlib import Path
import shutil

from ..errors import PublicationError
from .secure_copy import sync_directory


def publication_root(submission_root):
    root = Path(submission_root)
    if root.is_symlink():
        raise PublicationError("unsafe_submission_storage", "The submission storage root is not safe.", 500)
    try:
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        sync_directory(root.parent)
    except (OSError, RuntimeError) as exc:
        raise PublicationError("submission_storage_unavailable", "The submission storage root is unavailable.", 503) from exc
    if not root.is_dir():
        raise PublicationError("submission_storage_unavailable", "The submission storage root is unavailable.", 503)
    return root


def ensure_publication_directories(root, *components):
    current = root
    for component in components:
        candidate = current / component
        try:
            if candidate.is_symlink():
                raise PublicationError("unsafe_submission_storage", "The submission storage contains an unsafe link.", 500)
            candidate.mkdir(mode=0o750, exist_ok=True)
            sync_directory(current)
            resolved = candidate.resolve(strict=True)
        except PublicationError:
            raise
        except (OSError, RuntimeError) as exc:
            raise PublicationError("submission_storage_unavailable", "The submission storage is unavailable.", 503) from exc
        if resolved.parent != current:
            raise PublicationError("unsafe_submission_storage", "The submission storage path escaped its configured root.", 500)
        current = resolved
    return current


def discard_owned_staging(layout):
    """Remove only the deterministic staging directory owned by a submission."""

    staging = layout.staging_directory
    if not staging.exists() and not staging.is_symlink():
        return
    if staging.parent != layout.final_directory.parent or staging.is_symlink():
        raise PublicationError("unsafe_submission_storage", "The submission staging path is unsafe.", 500)
    if not staging.is_dir():
        raise PublicationError("unsafe_submission_storage", "The submission staging path is not a directory.", 500)
    shutil.rmtree(staging)
