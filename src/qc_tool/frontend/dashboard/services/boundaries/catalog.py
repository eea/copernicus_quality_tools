"""Bounded, read-only listings for an active boundary generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import BoundaryPackageLimits
from .errors import BoundaryCatalogLimitExceeded
from .errors import BoundaryGenerationUnavailable
from .errors import BoundaryPackageConfigurationError
from .errors import BoundaryPackageError


MAX_BOUNDARY_CATALOG_ENTRIES = BoundaryPackageLimits().max_members
_SUFFIXES = {
    "raster": frozenset({".tif"}),
    "vector": frozenset({".shp", ".gpkg"}),
}


@dataclass(frozen=True)
class BoundaryFile:
    """Display-safe metadata for one regular boundary file."""

    filename: str
    size_bytes: int
    boundary_type: str

    def as_dict(self):
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "type": self.boundary_type,
        }


def list_boundary_files(
    directory,
    boundary_type,
    *,
    max_entries=MAX_BOUNDARY_CATALOG_ENTRIES,
):
    """List matching files while bounding recursive filesystem work.

    The upload service already caps archive members. This independent read
    bound also protects installations that contain a legacy or manually
    provisioned generation.
    """

    try:
        suffixes = _SUFFIXES[boundary_type]
    except KeyError as error:
        raise ValueError("Boundary type must be raster or vector.") from error
    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or max_entries <= 0
    ):
        raise ValueError("max_entries must be a positive integer.")

    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise BoundaryGenerationUnavailable(
            "boundary catalog root is unavailable"
        )

    records = []
    try:
        for scanned_entries, path in enumerate(root.rglob("*"), start=1):
            if scanned_entries > max_entries:
                raise BoundaryCatalogLimitExceeded(
                    "boundary catalog scan limit exceeded"
                )
            if path.is_symlink():
                raise BoundaryPackageConfigurationError(
                    "boundary catalog contains a symbolic link"
                )
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            records.append(
                BoundaryFile(
                    filename=path.name,
                    size_bytes=path.stat().st_size,
                    boundary_type=boundary_type,
                )
            )
    except BoundaryPackageError:
        raise
    except OSError as error:
        raise BoundaryGenerationUnavailable(
            "boundary catalog could not be read"
        ) from error

    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.filename.casefold(),
                record.filename,
            ),
        )
    )
