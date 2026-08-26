"""Publication of an immutable boundary generation directory."""

import os
from pathlib import Path

from ..errors import BoundaryPackagePromotionError
from ..layout import generation_dir, generations_dir, path_lexists
from .durability import fsync_directory
from .trees import (
    freeze_generation_tree,
    prepare_managed_directory,
    validate_generation_tree,
)


def publish_generation(root: Path, payload_dir: Path, generation_id: str) -> Path:
    """Move one complete payload into the immutable generations namespace."""

    parent = prepare_managed_directory(generations_dir(root), mode=0o750)
    destination = generation_dir(root, generation_id)
    if path_lexists(destination):
        raise BoundaryPackagePromotionError("boundary generation already exists")

    validate_generation_tree(payload_dir)
    try:
        os.replace(payload_dir, destination)
        freeze_generation_tree(destination)
        fsync_directory(destination)
        fsync_directory(parent)
    except OSError as exc:
        # A possibly complete generation is retained for audit. It remains
        # inactive until the current pointer is replaced.
        raise BoundaryPackagePromotionError("generation publication failed") from exc
    return destination
