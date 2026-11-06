"""Compatibility exports; shared boundary contracts live in ``qc_tool.boundaries``."""

from qc_tool.boundaries.errors import (
    BoundaryPackageError,
    BoundaryPackageInvalid,
    BoundaryPackageUnsafe,
    BoundaryPackageLimitExceeded,
    BoundaryPackageInsufficientSpace,
    BoundaryCatalogLimitExceeded,
    BoundaryPackageBusy,
    BoundaryPackageConfigurationError,
    BoundaryGenerationUnavailable,
    BoundaryPackageInternalError,
    BoundaryPackagePromotionError,
)

__all__ = (
    "BoundaryPackageError",
    "BoundaryPackageInvalid",
    "BoundaryPackageUnsafe",
    "BoundaryPackageLimitExceeded",
    "BoundaryPackageInsufficientSpace",
    "BoundaryCatalogLimitExceeded",
    "BoundaryPackageBusy",
    "BoundaryPackageConfigurationError",
    "BoundaryGenerationUnavailable",
    "BoundaryPackageInternalError",
    "BoundaryPackagePromotionError",
)
