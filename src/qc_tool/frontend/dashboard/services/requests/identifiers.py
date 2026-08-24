"""Bounded parsing of comma-separated database identifiers."""

import re
from uuid import UUID


_POSITIVE_IDENTIFIER = re.compile(r"[1-9][0-9]{0,18}\Z", re.ASCII)


class IdentifierListError(ValueError):
    """A safe validation error suitable for a browser JSON response."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_positive_identifier_list(value, *, maximum_items=100):
    """Return unique positive integer IDs from one bounded canonical string."""

    parts = _parts(value, maximum_items=maximum_items)
    if any(not _POSITIVE_IDENTIFIER.fullmatch(part) for part in parts):
        raise IdentifierListError(
            "invalid_identifiers",
            "Identifiers must be comma-separated positive integers.",
        )
    return _unique(tuple(int(part) for part in parts))


def parse_uuid_identifier_list(value, *, maximum_items=100):
    """Return unique UUID objects from one bounded comma-separated string."""

    parts = _parts(value, maximum_items=maximum_items)
    try:
        values = tuple(UUID(part) for part in parts)
    except (AttributeError, TypeError, ValueError):
        raise IdentifierListError(
            "invalid_identifiers",
            "Identifiers must be comma-separated UUIDs.",
        )
    return _unique(values)


def _parts(value, *, maximum_items):
    if (
        isinstance(maximum_items, bool)
        or not isinstance(maximum_items, int)
        or maximum_items <= 0
    ):
        raise ValueError("maximum_items must be a positive integer")
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum_items * 40
    ):
        raise IdentifierListError(
            "invalid_identifiers",
            "Select at least one valid item.",
        )
    parts = tuple(value.split(","))
    if len(parts) > maximum_items or any(not part for part in parts):
        raise IdentifierListError(
            "invalid_identifiers",
            "Select a smaller set of valid items.",
        )
    return parts


def _unique(values):
    if len(set(values)) != len(values):
        raise IdentifierListError(
            "duplicate_identifiers",
            "An item may be selected only once.",
        )
    return values
