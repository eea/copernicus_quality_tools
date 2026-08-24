"""Validation for product configuration trust boundaries."""

from .definitions import UnsafeProductDefinition
from .definitions import validate_executable_product_configuration


__all__ = (
    "UnsafeProductDefinition",
    "validate_executable_product_configuration",
)
