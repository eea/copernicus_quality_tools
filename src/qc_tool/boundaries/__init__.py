"""Framework-independent boundary identities and snapshot resolution.

Frontend services own upload/activation; workers only resolve one immutable
snapshot. This package must not import frontend adapters or QC checks.
"""

from .contracts import BoundaryGeneration, BoundaryPackageLimits, BoundaryPackageResult
from .errors import BoundaryGenerationUnavailable, BoundaryPackageConfigurationError
from .resolver import resolve_boundary_generation

__all__ = (
    "BoundaryGeneration", "BoundaryGenerationUnavailable",
    "BoundaryPackageConfigurationError", "BoundaryPackageLimits",
    "BoundaryPackageResult", "resolve_boundary_generation",
)
