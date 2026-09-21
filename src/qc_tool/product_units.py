"""Opaque business unit identifiers and explicit legacy geographic adapters.

Product units are not geometries. Their identifiers retain numeric padding and
product-specific suffixes; only surrounding whitespace and case are normalized.
Geographic naming contracts are interpreted only at their legacy boundaries.
"""

import unicodedata

from qc_tool.aoi import is_aoi_input_alias, normalize_aoi_code


PRODUCT_UNIT_CODE_KEY = "product_unit_code"
PRODUCT_UNIT_CODE_MAX_LENGTH = 255
_REJECTED_CATEGORIES = frozenset(("Cc", "Cf", "Cs"))


def normalize_product_unit_code(value):
    """Return a bounded opaque identifier without geographic rewriting."""

    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    if (
        not value or len(value) > PRODUCT_UNIT_CODE_MAX_LENGTH
        or any(unicodedata.category(character) in _REJECTED_CATEGORIES for character in value)
    ):
        return None
    return value


def legacy_aoi_to_product_unit_code(value):
    """Translate an existing geographic naming/result value at its boundary."""

    return normalize_aoi_code(value)


def is_product_unit_input_alias(key):
    """Identify unit fields to replace with persisted facts in public reports."""

    return bool(
        key in (PRODUCT_UNIT_CODE_KEY, "verified_product_unit_code", "submitted_product_unit_code", "aoi_code_submitted")
        or is_aoi_input_alias(key)
    )
