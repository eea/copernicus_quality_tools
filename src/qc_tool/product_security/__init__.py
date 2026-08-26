"""Validation for product configuration trust boundaries."""

from .definitions import UnsafeProductDefinition
from .definitions import validate_executable_product_configuration
from .identifiers import canonical_product_ident
from .identifiers import normalize_product_ident
from .identifiers import RESERVED_PRODUCT_IDENTS


__all__ = (
    "UnsafeProductDefinition",
    "RESERVED_PRODUCT_IDENTS",
    "canonical_product_ident",
    "normalize_product_ident",
    "validate_executable_product_configuration",
)
