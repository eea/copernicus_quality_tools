"""Spreadsheet-safe value conversion for user-controlled delivery metadata."""


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def spreadsheet_cell_value(value):
    """Prevent exported text from being interpreted as an active formula."""

    if isinstance(value, str) and (
        value.startswith(_FORMULA_PREFIXES)
        or value.lstrip().startswith(_FORMULA_PREFIXES)
    ):
        return "'" + value
    return value
