"""Canonical product identifiers shared by catalog trust boundaries."""

import re


MAX_PRODUCT_IDENT_LENGTH = 64
RESERVED_PRODUCT_IDENTS = frozenset({"list", "upload", "submissions"})
_PRODUCT_IDENT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")


def normalize_product_ident(value):
    """Return a canonical identifier or ``None`` for an invalid value."""

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.isascii()
    ):
        return None
    normalized = value.casefold()
    if (
        len(normalized) > MAX_PRODUCT_IDENT_LENGTH
        or _PRODUCT_IDENT_PATTERN.fullmatch(normalized) is None
        or normalized in RESERVED_PRODUCT_IDENTS
    ):
        return None
    return normalized


def canonical_product_ident(value):
    """Return ``value`` only when it is already canonical and routable."""

    normalized = normalize_product_ident(value)
    return value if value == normalized else None
