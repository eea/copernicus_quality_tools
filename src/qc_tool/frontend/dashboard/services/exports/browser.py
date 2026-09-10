"""Validate a bounded table snapshot supplied by an authenticated browser.

This is file conversion, not a database query or an authoritative data import.
It never resolves identifiers, URLs or filenames to application resources.
"""

import json
import math
import re
from dataclasses import dataclass

from .tabular import ExportColumn, InvalidTableExport, export_format, tabular_cell_value


MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_EXPORT_COLUMNS = 256
MAX_EXPORT_ROWS = 50_000
MAX_EXPORT_CELLS = 500_000
_SURROGATE = re.compile(r"[\ud800-\udfff]")


@dataclass(frozen=True)
class BrowserTableExport:
    format: str
    filename: str
    columns: tuple[ExportColumn, ...]
    rows: list[dict]


def _text(value, maximum):
    return isinstance(value, str) and len(value) <= maximum and not _SURROGATE.search(value)


def _validate_value(value, depth=0):
    if depth > 32:
        raise InvalidTableExport("Export metadata is nested too deeply.")
    if isinstance(value, str):
        if not _text(value, 32_767):
            raise InvalidTableExport("A text cell is too long or contains invalid Unicode.")
    elif isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise InvalidTableExport("Export numbers must be finite.")
    elif isinstance(value, list):
        for item in value:
            _validate_value(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not _text(key, 32_767):
                raise InvalidTableExport("Export metadata contains an invalid key.")
            _validate_value(item, depth + 1)


def parse_browser_export(body):
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InvalidTableExport("Provide a valid JSON table export request.") from error
    if not isinstance(payload, dict) or set(payload) - {"format", "filename", "columns", "rows"}:
        raise InvalidTableExport("Provide format, filename, columns and rows for the export.")

    format = export_format(payload.get("format") or "")
    filename = payload.get("filename", "table")
    if not _text(filename, 120) or not re.fullmatch(r"\w[\w .-]*", filename):
        raise InvalidTableExport("Choose a filename without paths or special characters.")
    filename = re.sub(r"\.(json|csv|xlsx|xml)$", "", filename, flags=re.IGNORECASE)
    definitions = payload.get("columns")
    rows = payload.get("rows")
    if not isinstance(definitions, list) or not 1 <= len(definitions) <= MAX_EXPORT_COLUMNS:
        raise InvalidTableExport(f"Choose between 1 and {MAX_EXPORT_COLUMNS} data columns.")
    columns = []
    fields = set()
    for column in definitions:
        if not isinstance(column, dict) or set(column) != {"field", "label"}:
            raise InvalidTableExport("Each export column needs a field and a label.")
        field, label = column["field"], column["label"]
        if not _text(field, 128) or not field or not _text(label, 200) or not label or field in fields:
            raise InvalidTableExport("Export columns need unique fields and valid labels.")
        fields.add(field)
        columns.append(ExportColumn(field, label))
    if not isinstance(rows, list) or len(rows) > MAX_EXPORT_ROWS or len(rows) * len(columns) > MAX_EXPORT_CELLS:
        raise InvalidTableExport("This table is too large for a browser snapshot. Narrow the filters and try again.")
    for row in rows:
        if not isinstance(row, dict) or set(row) - fields:
            raise InvalidTableExport("Export rows must contain only the declared data fields.")
        _validate_value(row)
        for value in row.values():
            rendered = tabular_cell_value(value)
            if isinstance(rendered, str) and len(rendered) > 32_767:
                raise InvalidTableExport("A cell is too long to export without losing content.")
    return BrowserTableExport(format, filename, tuple(columns), rows)
