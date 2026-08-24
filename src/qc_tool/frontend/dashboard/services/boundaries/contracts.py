"""Public value objects for boundary-package activation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Mapping


LIVE_DIRECTORY_NAMES = ("raster", "vector")


@dataclass(frozen=True)
class BoundaryPackageLimits:
    """Resource limits applied before an uploaded archive can be activated.

    Deployments with legitimately larger geospatial packages can pass an
    explicit instance. Keeping these values together makes exceptions visible
    and reviewable instead of scattering magic limits through an HTTP view.
    """

    max_archive_bytes: int = 512 * 1024 * 1024
    max_members: int = 10_000
    max_member_bytes: int = 512 * 1024 * 1024
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_path_length: int = 1_024
    max_path_component_bytes: int = 255
    max_path_depth: int = 32

    def __post_init__(self) -> None:
        for field_name in (
            "max_archive_bytes",
            "max_members",
            "max_member_bytes",
            "max_uncompressed_bytes",
            "max_path_length",
            "max_path_component_bytes",
            "max_path_depth",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be greater than zero")
        ratio = self.max_compression_ratio
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
            raise ValueError("max_compression_ratio must be numeric")
        if not math.isfinite(ratio) or ratio < 1:
            raise ValueError("max_compression_ratio must be finite and at least 1")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "BoundaryPackageLimits":
        """Build limits from a settings-like mapping, ignoring unrelated keys."""

        field_names = cls.__dataclass_fields__.keys()
        return cls(**{name: values[name] for name in field_names if name in values})


@dataclass(frozen=True)
class BoundaryPackageResult:
    """Non-sensitive audit information for a successful activation."""

    sha256: str
    archive_size: int
    member_count: int
    file_count: int
    uncompressed_size: int
    generation_id: str


@dataclass(frozen=True)
class BoundaryGeneration:
    """One pinned boundary snapshot safe for a multi-file reader."""

    generation_id: str
    path: Path
    raster_dir: Path
    vector_dir: Path
    managed: bool
