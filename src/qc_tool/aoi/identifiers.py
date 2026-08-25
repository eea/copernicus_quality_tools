"""Normalize product-specific AOI labels into one application contract.

This module is dependency-free and Python 3.8-compatible so the Django
frontend and worker can use exactly the same rules.  It intentionally knows
nothing about product definitions, boundary files, or spatial QC checks.
"""

import re
import unicodedata

from .constants import AOI_CODE_KEY
from .constants import AOI_CODE_MAX_LENGTH
from .constants import AOI_INPUT_ALIASES


_STANDARD_AOI_PATTERNS = (
    # Urban Atlas names may add a sub-unit/revision suffix.  The stable FUA
    # identifier used in persisted metadata is the six-character prefix.
    re.compile(
        r"^(?P<aoi_code>[a-z]{2}[0-9]{3}l)(?:[0-9xy])?$",
        re.IGNORECASE,
    ),
    # N2K delivery names may add a letter suffix to their shared DU code.
    re.compile(r"^(?P<aoi_code>du[0-9]{3})(?:[a-z])?$", re.IGNORECASE),
)
_REJECTED_UNICODE_CATEGORIES = frozenset(("Cc", "Cf", "Cs"))


def _normalize_alias(alias):
    if not isinstance(alias, str):
        return None
    return re.sub(r"[^a-z0-9]", "", alias.casefold())


_NORMALIZED_INPUT_ALIASES = tuple(
    dict.fromkeys(_normalize_alias(alias) for alias in AOI_INPUT_ALIASES)
)


def is_aoi_input_alias(alias):
    """Return whether *alias* is a supported external AOI field name."""

    return _normalize_alias(alias) in _NORMALIZED_INPUT_ALIASES


def aoi_input_aliases_equivalent(first, second):
    """Compare AOI field names case- and separator-insensitively."""

    first_normalized = _normalize_alias(first)
    return (
        first_normalized is not None
        and first_normalized == _normalize_alias(second)
    )


def normalize_aoi_code(value):
    """Return the stable lowercase AOI identifier, or ``None`` if invalid."""

    if not isinstance(value, str):
        return None

    normalized = value.strip().casefold()
    if (
        not normalized
        or len(normalized) > AOI_CODE_MAX_LENGTH
        or any(
            unicodedata.category(character) in _REJECTED_UNICODE_CATEGORIES
            for character in normalized
        )
    ):
        return None

    for pattern in _STANDARD_AOI_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return match.group(AOI_CODE_KEY).casefold()

    # Some combined products use both padded and unpadded numeric AOIs. Store
    # one representation so equivalent values cannot become distinct indexed
    # database values (for example, ``007`` and ``7``).
    if normalized.isdecimal():
        return str(int(normalized))
    return normalized


def aoi_codes_equivalent(first, second):
    """Return whether two product-specific AOI values identify one AOI."""

    first_normalized = normalize_aoi_code(first)
    second_normalized = normalize_aoi_code(second)
    if first_normalized is None or second_normalized is None:
        return False
    if first_normalized == second_normalized:
        return True

    # Combined products historically use padded and unpadded numeric forms.
    if first_normalized.isdecimal() and second_normalized.isdecimal():
        return int(first_normalized) == int(second_normalized)
    return False


def has_aoi_code_capture(regex):
    """Return whether a regular expression declares a known AOI group."""

    return any(
        is_aoi_input_alias(group_name)
        for group_name in re.compile(regex).groupindex
    )


def extract_aoi_code_from_groups(groups):
    """Resolve named capture groups to one unambiguous raw AOI value.

    More than one alias is permitted only when all populated values are
    equivalent. Conflicting captures raise :class:`ValueError` so callers
    fail closed instead of choosing an arbitrary identifier.
    """

    if not isinstance(groups, dict):
        return None

    candidates = []
    for alias_index, normalized_alias in enumerate(_NORMALIZED_INPUT_ALIASES):
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
    if any(
        not aoi_codes_equivalent(selected, candidate[1])
        for candidate in candidates[1:]
    ):
        raise ValueError("AOI capture groups contain conflicting values")
    return selected


def with_canonical_aoi_capture(groups):
    """Return capture groups with a derived canonical ``aoi_code`` key.

    Original aliases are retained for compatibility with downstream product
    checks. Only the derived canonical key crosses the result/database/API
    boundary.
    """

    if not isinstance(groups, dict):
        return {}
    enriched_groups = dict(groups)
    aoi_code = extract_aoi_code_from_groups(groups)
    if aoi_code is not None:
        enriched_groups[AOI_CODE_KEY] = aoi_code
    return enriched_groups


def canonicalize_aoi_capture_groups(groups):
    """Return capture groups using only ``aoi_code`` for the AOI concept.

    This stricter projection is suitable for public metadata. Naming checks
    should use :func:`with_canonical_aoi_capture` when legacy aliases must
    remain available internally.
    """

    enriched_groups = with_canonical_aoi_capture(groups)
    canonical_groups = {
        group_name: value
        for group_name, value in enriched_groups.items()
        if not is_aoi_input_alias(group_name) or group_name == AOI_CODE_KEY
    }
    if AOI_CODE_KEY in canonical_groups:
        canonical_groups[AOI_CODE_KEY] = normalize_aoi_code(
            canonical_groups[AOI_CODE_KEY]
        )
    return canonical_groups
