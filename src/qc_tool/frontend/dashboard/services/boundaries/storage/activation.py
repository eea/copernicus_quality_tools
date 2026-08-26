"""Atomic selection of the active published boundary generation."""

import logging
import os
from pathlib import Path
import uuid

from ..errors import BoundaryPackageConfigurationError, BoundaryPackagePromotionError
from ..layout import (
    CURRENT_POINTER_NAME,
    current_pointer,
    current_pointer_target,
    generation_dir,
    path_lexists,
)
from .durability import fsync_directory
from .trees import validate_published_generation


logger = logging.getLogger(__name__)


def activate_generation(root: Path, generation_id: str) -> None:
    """Atomically replace the single pointer selecting the active package."""

    destination = generation_dir(root, generation_id)
    validate_published_generation(destination)
    pointer = current_pointer(root)
    if path_lexists(pointer) and not pointer.is_symlink():
        raise BoundaryPackageConfigurationError("boundary current pointer is not a symlink")

    temporary_pointer = root / f".{CURRENT_POINTER_NAME}.tmp-{uuid.uuid4().hex}"
    try:
        os.symlink(current_pointer_target(generation_id), temporary_pointer)
        os.replace(temporary_pointer, pointer)
        fsync_directory(root)
    except OSError as exc:
        raise BoundaryPackagePromotionError(
            "active generation pointer update failed"
        ) from exc
    finally:
        try:
            temporary_pointer.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove a temporary boundary pointer")
