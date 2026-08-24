"""Resolve and pin one active boundary generation for readers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from .contracts import BoundaryGeneration, LIVE_DIRECTORY_NAMES
from .errors import (
    BoundaryGenerationUnavailable,
    BoundaryPackageConfigurationError,
)
from .layout import (
    CURRENT_POINTER_NAME,
    GENERATIONS_DIRECTORY_NAME,
    current_pointer,
    current_pointer_target,
    path_lexists,
    validate_generation_id,
)


def resolve_boundary_generation(
    boundary_dir: Union[str, os.PathLike],
    *,
    allow_legacy: bool = True,
) -> BoundaryGeneration:
    """Resolve the current pointer once and return stable paths.

    Callers must retain and reuse the returned object for all files involved in
    one request or QC job. Re-resolving between file opens could intentionally
    pick up a newer generation and lose snapshot consistency.
    """

    root = Path(boundary_dir)
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BoundaryGenerationUnavailable("boundary root is unavailable") from exc
    if not root.is_dir():
        raise BoundaryGenerationUnavailable("boundary root is not a directory")

    pointer = current_pointer(root)
    if path_lexists(pointer):
        return _resolve_managed_generation(root, pointer)
    if allow_legacy:
        return _resolve_legacy_generation(root)
    raise BoundaryGenerationUnavailable("managed boundary pointer is missing")


def _resolve_managed_generation(root: Path, pointer: Path) -> BoundaryGeneration:
    if not pointer.is_symlink():
        raise BoundaryPackageConfigurationError("boundary current pointer is not a symlink")

    try:
        raw_target = os.readlink(pointer)
    except OSError as exc:
        raise BoundaryPackageConfigurationError("boundary current pointer cannot be read") from exc

    target_parts = Path(raw_target).parts
    if (
        Path(raw_target).is_absolute()
        or "\\" in raw_target
        or len(target_parts) != 2
        or target_parts[0] != GENERATIONS_DIRECTORY_NAME
    ):
        raise BoundaryPackageConfigurationError("boundary current pointer target is unsafe")
    generation_id = validate_generation_id(target_parts[1])
    if raw_target != current_pointer_target(generation_id):
        raise BoundaryPackageConfigurationError("boundary current pointer is not canonical")

    generation_candidate = root / raw_target
    generations_candidate = root / GENERATIONS_DIRECTORY_NAME
    if generation_candidate.is_symlink() or generations_candidate.is_symlink():
        raise BoundaryPackageConfigurationError("boundary generation storage contains a link")
    try:
        generation_path = generation_candidate.resolve(strict=True)
        expected_parent = generations_candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BoundaryGenerationUnavailable("active boundary generation is unavailable") from exc
    if generation_path.parent != expected_parent or generation_path.is_symlink():
        raise BoundaryPackageConfigurationError("active boundary generation escapes storage")

    directories = _validated_generation_directories(generation_path)
    return BoundaryGeneration(
        generation_id=generation_id,
        path=generation_path,
        raster_dir=directories["raster"],
        vector_dir=directories["vector"],
        managed=True,
    )


def _resolve_legacy_generation(root: Path) -> BoundaryGeneration:
    directories = {}
    for name in LIVE_DIRECTORY_NAMES:
        path = root / name
        if path.is_symlink() or not path.is_dir():
            raise BoundaryGenerationUnavailable("legacy boundary directories are incomplete")
        directories[name] = path.resolve(strict=True)
    return BoundaryGeneration(
        generation_id="legacy-unmanaged",
        path=root,
        raster_dir=directories["raster"],
        vector_dir=directories["vector"],
        managed=False,
    )


def _validated_generation_directories(generation_path: Path) -> dict[str, Path]:
    if generation_path.is_symlink() or not generation_path.is_dir():
        raise BoundaryPackageConfigurationError("boundary generation is not a directory")
    directories = {}
    for name in LIVE_DIRECTORY_NAMES:
        path = generation_path / name
        if path.is_symlink() or not path.is_dir():
            raise BoundaryPackageConfigurationError(
                f"boundary generation {name} directory is invalid"
            )
        directories[name] = path
    return directories
