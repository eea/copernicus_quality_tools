"""Typed, user-safe boundary-package failures."""

from __future__ import annotations

import math
from typing import Optional


def _size(value: int) -> str:
    for unit, divisor in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if value >= divisor:
            return f"{value / divisor:.2f} {unit}"
    return f"{value:,} bytes"


class BoundaryPackageError(Exception):
    """Base class for errors that HTTP handlers may safely translate."""

    code = "boundary_package_error"
    user_message = "The boundary package could not be processed."
    status_code = 400

    def __init__(self, detail: Optional[str] = None) -> None:
        # Keep diagnostic detail off the exception string as defense in depth:
        # even an integration that returns str(exc) cannot expose internals.
        super().__init__(self.user_message)
        self.detail = detail


class BoundaryPackageInvalid(BoundaryPackageError):
    code = "invalid_boundary_package"
    user_message = "The uploaded file is not a valid boundary package ZIP."


class BoundaryPackageUnsafe(BoundaryPackageError):
    code = "unsafe_boundary_package"
    user_message = "The boundary package contains an unsafe file path or entry type."


class BoundaryPackageLimitExceeded(BoundaryPackageError):
    code = "boundary_package_limit_exceeded"
    user_message = "The boundary package exceeds the configured safety limits."
    status_code = 413

    def __init__(self, detail=None, *, limit=None, actual=None, maximum=None):
        # Only fixed labels and numeric measurements may reach the UI. A ZIP
        # member name, filesystem path or diagnostic detail never becomes copy.
        labels = {
            "archive_bytes": ("Boundary ZIP size", _size),
            "member_bytes": ("A boundary file's expanded size", _size),
            "uncompressed_bytes": ("Expanded boundary package size", _size),
            "members": ("ZIP entry count", lambda value: f"{value:,}"),
            "path_bytes": ("ZIP path length in bytes", lambda value: f"{value:,}"),
            "component_bytes": ("ZIP filename length in bytes", lambda value: f"{value:,}"),
            "path_depth": ("ZIP path depth", lambda value: f"{value:,}"),
            "compression_ratio": ("ZIP compression ratio", lambda value: f"{value:.2f}×"),
        }
        self.limit, self.actual, self.maximum = limit, actual, maximum
        if limit is not None:
            if limit not in labels or type(maximum) not in (int, float) or not math.isfinite(maximum) or maximum <= 0:
                raise ValueError("Boundary limit metadata must contain a supported limit and positive maximum.")
            if actual is not None and (type(actual) not in (int, float) or not math.isfinite(actual) or actual < 0):
                raise ValueError("Boundary limit metadata must contain a non-negative measurement.")
            label, formatter = labels[limit]
            observed = f" reached {formatter(actual)} and" if actual is not None else ""
            self.user_message = f"{label}{observed} exceeds the configured limit of {formatter(maximum)}."
        super().__init__(detail)


class BoundaryPackageInsufficientSpace(BoundaryPackageError):
    code = "boundary_package_insufficient_space"
    status_code = 507

    def __init__(self, *, required_bytes=None, available_bytes=None):
        measured = required_bytes is not None or available_bytes is not None
        if measured and (type(required_bytes) is not int or required_bytes < 0
                         or type(available_bytes) is not int or available_bytes < 0):
            raise ValueError("Boundary capacity measurements must be non-negative bytes.")
        self.required_bytes, self.available_bytes = required_bytes, available_bytes
        if measured:
            self.user_message = (
                f"Not enough boundary storage space: need {_size(required_bytes)} free, "
                f"but {_size(available_bytes)} is available. The current package remains active."
            )
        else:
            self.user_message = "Boundary storage ran out of usable space. The current package remains active."
        super().__init__("insufficient free space before boundary extraction")


class BoundaryCatalogLimitExceeded(BoundaryPackageLimitExceeded):
    code = "boundary_catalog_limit_exceeded"
    user_message = (
        "The active boundary package contains too many entries to list safely."
    )


class BoundaryPackageBusy(BoundaryPackageError):
    code = "boundary_package_busy"
    user_message = "Another boundary package update is in progress. Please try again."
    status_code = 409


class BoundaryPackageConfigurationError(BoundaryPackageError):
    code = "boundary_package_configuration_error"
    user_message = "Boundary package storage or safety limits are not configured safely."
    status_code = 500


class BoundaryGenerationUnavailable(BoundaryPackageConfigurationError):
    code = "boundary_generation_unavailable"
    user_message = "No active boundary package is available."
    status_code = 503


class BoundaryPackageInternalError(BoundaryPackageError):
    code = "boundary_package_internal_error"
    user_message = "The boundary package could not be processed safely."
    status_code = 500


class BoundaryPackagePromotionError(BoundaryPackageError):
    code = "boundary_package_promotion_failed"
    user_message = (
        "The boundary package was validated, but activation could not be confirmed. "
        "Check the active boundaries before retrying."
    )
    status_code = 500
