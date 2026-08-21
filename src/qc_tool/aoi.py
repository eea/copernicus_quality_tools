#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re


AOI_CODE_KEY = "aoi_code"

# Product definitions and external datasets use several names for the same
# identifier. These spellings are accepted only at the naming/input boundary;
# all internal and persisted metadata uses AOI_CODE_KEY.
_AOI_INPUT_ALIASES = (
    AOI_CODE_KEY,
    "delivery_unit_id",
    "fua_code",
    "fua",
    "du_id",
    "du",
    "code_city",
    "codecity",
)

_STANDARD_AOI_PATTERNS = (
    # Legacy Urban Atlas names include a final sub-unit/revision digit, while
    # current names and boundary data use the six-character FUA identifier.
    re.compile(r"^(?P<aoi_code>[a-z]{2}[0-9]{3}l)(?:[0-9])?$", re.IGNORECASE),
    # N2K delivery names include a letter suffix, while their shared delivery
    # unit identifier and the related RPZ products use DU plus three digits.
    re.compile(r"^(?P<aoi_code>du[0-9]{3})(?:[a-z])?$", re.IGNORECASE),
)


def _normalize_alias(alias):
    if not isinstance(alias, str):
        return None
    return re.sub(r"[^a-z0-9]", "", alias.casefold())


_NORMALIZED_AOI_INPUT_ALIASES = tuple(dict.fromkeys(
    _normalize_alias(alias) for alias in _AOI_INPUT_ALIASES
))


def is_aoi_input_alias(alias):
    """Return whether *alias* is an accepted input spelling for an AOI code."""
    return _normalize_alias(alias) in _NORMALIZED_AOI_INPUT_ALIASES


def normalize_aoi_code(value):
    """Return the stable lowercase AOI identifier used in results and the DB."""
    if not isinstance(value, str):
        return None

    normalized = value.strip().casefold()
    if not normalized:
        return None

    for pattern in _STANDARD_AOI_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return match.group(AOI_CODE_KEY).casefold()
    return normalized


def aoi_codes_equivalent(first, second):
    """Compare AOI values without rewriting the product-specific raw value."""
    first_normalized = normalize_aoi_code(first)
    second_normalized = normalize_aoi_code(second)
    if first_normalized is None or second_normalized is None:
        return False
    if first_normalized == second_normalized:
        return True

    # Some combined raster/vector products use zero-padded and unpadded forms
    # for the same numeric AOI. Keep the first form but compare by value.
    if first_normalized.isdecimal() and second_normalized.isdecimal():
        return int(first_normalized) == int(second_normalized)
    return False


def has_aoi_code_capture(regex):
    """Return whether a regular expression contains a known AOI code group."""
    return any(is_aoi_input_alias(group_name) for group_name in re.compile(regex).groupindex)


def extract_aoi_code_from_groups(groups):
    """Resolve product-specific named groups to one unambiguous AOI value.

    Alias names are matched case- and separator-insensitively. If a regex ever
    publishes more than one AOI alias, all populated values must be equivalent.
    The raw value from the preferred alias is returned so existing downstream
    product checks continue to receive the representation defined by that
    product. Call :func:`normalize_aoi_code` for result or database metadata.
    """
    if not isinstance(groups, dict):
        return None

    candidates = []
    for alias_index, normalized_alias in enumerate(_NORMALIZED_AOI_INPUT_ALIASES):
        for group_name, value in groups.items():
            if _normalize_alias(group_name) != normalized_alias:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            candidates.append((alias_index, value.strip()))

    if not candidates:
        return None

    candidates.sort(key=lambda candidate: candidate[0])
    selected = candidates[0][1]
    if any(not aoi_codes_equivalent(selected, candidate[1]) for candidate in candidates[1:]):
        raise ValueError("AOI capture groups contain conflicting values")
    return selected


def canonicalize_aoi_capture_groups(groups):
    """Replace every recognized AOI input group with only ``aoi_code``.

    Other named captures, such as ``epsg_code`` and ``fua_name``, are retained.
    The AOI value remains in its product-specific form for downstream checks;
    result and database metadata is normalized by :func:`normalize_aoi_code`.
    """
    if not isinstance(groups, dict):
        return {}

    aoi_code = extract_aoi_code_from_groups(groups)
    canonical_groups = {
        group_name: value
        for group_name, value in groups.items()
        if not is_aoi_input_alias(group_name)
    }
    if aoi_code is not None:
        canonical_groups[AOI_CODE_KEY] = aoi_code
    return canonical_groups
