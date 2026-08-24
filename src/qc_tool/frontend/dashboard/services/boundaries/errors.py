"""Typed, user-safe boundary-package failures."""

from __future__ import annotations

from typing import Optional


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


class BoundaryPackageBusy(BoundaryPackageError):
    code = "boundary_package_busy"
    user_message = "Another boundary package update is in progress. Please try again."
    status_code = 409


class BoundaryPackageConfigurationError(BoundaryPackageError):
    code = "boundary_package_configuration_error"
    user_message = "Boundary package storage is not configured safely."
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
        "The boundary package was validated but could not be activated. "
        "The previous package remains active."
    )
    status_code = 500
