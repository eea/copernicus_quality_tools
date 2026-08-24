"""Secure boundary-package replacement service.

The stable integration surface is ``replace_boundary_package`` plus the typed
contracts and failures exported here. Internal archive and storage mechanics
remain split into focused modules.
"""

from .contracts import (
    BoundaryGeneration,
    BoundaryPackageLimits,
    BoundaryPackageResult,
)
from .errors import (
    BoundaryGenerationUnavailable,
    BoundaryPackageBusy,
    BoundaryPackageConfigurationError,
    BoundaryPackageError,
    BoundaryPackageInternalError,
    BoundaryPackageInvalid,
    BoundaryPackageLimitExceeded,
    BoundaryPackagePromotionError,
    BoundaryPackageUnsafe,
)
from .resolver import resolve_boundary_generation
from .service import replace_boundary_package


__all__ = (
    "BoundaryGeneration",
    "BoundaryGenerationUnavailable",
    "BoundaryPackageBusy",
    "BoundaryPackageConfigurationError",
    "BoundaryPackageError",
    "BoundaryPackageInvalid",
    "BoundaryPackageInternalError",
    "BoundaryPackageLimitExceeded",
    "BoundaryPackageLimits",
    "BoundaryPackagePromotionError",
    "BoundaryPackageResult",
    "BoundaryPackageUnsafe",
    "replace_boundary_package",
    "resolve_boundary_generation",
)
