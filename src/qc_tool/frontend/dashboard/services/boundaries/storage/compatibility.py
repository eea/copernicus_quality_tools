"""Compatibility symlinks exposing managed generations at legacy paths."""

import logging
import os
from pathlib import Path
import uuid

from ..contracts import LIVE_DIRECTORY_NAMES
from ..errors import BoundaryPackageConfigurationError, BoundaryPackagePromotionError
from ..layout import compatibility_link_target, path_lexists
from .durability import fsync_directory


logger = logging.getLogger(__name__)


def ensure_fresh_compatibility_links(root: Path) -> None:
    """Install legacy raster/vector paths when neither contains old data."""

    for name in LIVE_DIRECTORY_NAMES:
        target = root / name
        if path_lexists(target):
            if not is_compatibility_link(root, name):
                raise BoundaryPackageConfigurationError(
                    f"legacy {name} path requires explicit migration"
                )
            continue
        _install_compatibility_link(root, name)
    fsync_directory(root)


def is_compatibility_link(root: Path, directory_name: str) -> bool:
    path = root / directory_name
    if not path.is_symlink():
        return False
    try:
        return os.readlink(path) == compatibility_link_target(directory_name)
    except OSError:
        return False


def _install_compatibility_link(root: Path, directory_name: str) -> None:
    target = root / directory_name
    temporary_link = root / f".boundary-link-{directory_name}-{uuid.uuid4().hex}"
    try:
        os.symlink(compatibility_link_target(directory_name), temporary_link)
        os.replace(temporary_link, target)
    except OSError as exc:
        raise BoundaryPackagePromotionError(
            "compatibility link installation failed"
        ) from exc
    finally:
        try:
            temporary_link.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove a temporary compatibility link")
