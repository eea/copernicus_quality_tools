"""Explicit, reusable column contracts for safe tabular downloads.

Callers provide access-scoped rows. Columns are never inferred from a row.
"""

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from tempfile import SpooledTemporaryFile
from typing import Callable, Mapping
from uuid import UUID
from xml.etree import ElementTree

import openpyxl
from django.core.serializers.json import DjangoJSONEncoder
from django.http import FileResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header

from .spreadsheets import spreadsheet_cell_value


_INVALID_XML_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
EXPORT_FORMAT_OPTIONS = tuple(
    {"value": value, "label": value.upper()} for value in ("json", "csv", "xlsx", "xml")
)
EXPORT_FORMATS = tuple(option["value"] for option in EXPORT_FORMAT_OPTIONS)
XLSX_MAX_ROWS = 1_048_576


class InvalidTableExport(ValueError):
    """A requested format or column is not part of the export contract."""


@dataclass(frozen=True)
class ExportColumn:
    field: str
    label: str
    value: Callable[[Mapping], object] | None = None

    def read(self, row):
        return self.value(row) if self.value is not None else row.get(self.field)


def export_format(value):
    """Validate an explicit format, keeping XLSX as the default."""

    if value is None:
        return "xlsx"
    if value not in EXPORT_FORMATS:
        raise InvalidTableExport("Choose JSON, CSV, XLSX or XML for the export.")
    return value


def select_export_columns(columns, requested=None):
    """Resolve a JSON array against the server's allowlist, preserving order."""

    columns = tuple(columns)
    if requested is None:
        return columns
    try:
        if not isinstance(requested, str) or len(requested) > 4096:
            raise ValueError
        fields = json.loads(requested)
        if not isinstance(fields, list) or not fields:
            raise ValueError
        if any(not isinstance(field, str) for field in fields):
            raise ValueError
        if len(set(fields)) != len(fields):
            raise ValueError
        available = {column.field: column for column in columns}
        return tuple(available[field] for field in fields)
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise InvalidTableExport("Choose at least one supported export column.") from exc


def tabular_cell_value(value):
    """Preserve scalar types and timezone information; serialize metadata.

    Datetimes use ISO 8601 text, since Excel dates cannot represent timezones.
    Both formats share formula neutralization, including converted values.
    """

    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        value = value.isoformat()
    elif isinstance(value, UUID):
        value = str(value)
    elif isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False)
    elif not isinstance(value, (str, int, float, bool)):
        value = str(value)
    if isinstance(value, str):
        value = _INVALID_XML_CHARACTERS.sub("", value)
    return spreadsheet_cell_value(value)


def tabular_rows(rows, columns):
    """Emit the declared header even when the result has no data rows."""

    yield [tabular_cell_value(column.label) for column in columns]
    for row in rows:
        yield [tabular_cell_value(column.read(row)) for column in columns]


class _CSVBuffer:
    def write(self, value):
        return value


def csv_chunks(rows, columns):
    """Stream UTF-8 CSV; the BOM lets desktop Excel recognize Unicode."""

    try:
        yield "\ufeff"
        writer = csv.writer(_CSVBuffer())
        for row in tabular_rows(rows, columns):
            yield writer.writerow(row)
    finally:
        if hasattr(rows, "close"):
            rows.close()


def json_chunks(rows, columns):
    """Stream field-keyed records without changing their values for spreadsheets."""

    try:
        yield "["
        separator = ""
        for row in rows:
            record = {column.field: column.read(row) for column in columns}
            yield separator + json.dumps(record, cls=DjangoJSONEncoder, ensure_ascii=False)
            separator = ","
        yield "]"
    finally:
        if hasattr(rows, "close"):
            rows.close()


def _xml_text(value):
    return _INVALID_XML_CHARACTERS.sub("", str(value))


def _xml_cell_value(value):
    if value is None:
        return "null", None
    if isinstance(value, bool):
        return "boolean", "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return "number", str(value)
    if isinstance(value, (dict, list, tuple)):
        return "json", json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False)
    if isinstance(value, (datetime, date, time)):
        value = value.isoformat()
    return "string", str(value)


def xml_chunks(rows, columns):
    """Stream a stable document whose user-provided names are only attributes.

    Cells distinguish nulls, strings, numbers, booleans, and JSON metadata.
    XML escaping belongs to the serializer; XML 1.0-invalid characters are
    removed from text and attributes so every download remains parseable.
    """

    try:
        yield '<?xml version="1.0" encoding="utf-8"?><table>'
        header = ElementTree.Element("columns")
        for column in columns:
            ElementTree.SubElement(header, "column", {
                "field": _xml_text(column.field), "label": _xml_text(column.label),
            })
        yield ElementTree.tostring(header, encoding="unicode")
        yield "<rows>"
        for row in rows:
            element = ElementTree.Element("row")
            for column in columns:
                type_name, value = _xml_cell_value(column.read(row))
                cell = ElementTree.SubElement(element, "cell", {
                    "field": _xml_text(column.field), "type": type_name,
                })
                if value is not None:
                    cell.text = _xml_text(value)
            yield ElementTree.tostring(element, encoding="unicode")
        yield "</rows></table>"
    finally:
        if hasattr(rows, "close"):
            rows.close()


def write_xlsx(rows, columns, destination, *, sheet_name="Data"):
    """Write rows incrementally instead of retaining a worksheet in memory."""

    workbook = openpyxl.Workbook(write_only=True)
    columns = tuple(columns)
    header = [tabular_cell_value(column.label) for column in columns]

    def add_sheet():
        suffix = f" {len(workbook.worksheets) + 1}" if workbook.worksheets else ""
        worksheet = workbook.create_sheet(sheet_name[:31 - len(suffix)] + suffix)
        worksheet.freeze_panes = "A2"
        worksheet.append(header)
        return worksheet

    worksheet = add_sheet()
    row_count = 1
    try:
        for row in rows:
            if row_count >= XLSX_MAX_ROWS:
                worksheet = add_sheet()
                row_count = 1
            worksheet.append([tabular_cell_value(column.read(row)) for column in columns])
            row_count += 1
        workbook.save(destination)
    finally:
        workbook.close()
        if hasattr(rows, "close"):
            rows.close()


def table_export_response(rows, columns, *, format, filename, sheet_name="Data"):
    """Create a download; the web server closes any spooled XLSX file."""

    format = export_format(format)
    columns = tuple(columns)
    streams = {
        "json": (json_chunks, "application/json; charset=utf-8"),
        "csv": (csv_chunks, "text/csv; charset=utf-8"),
        "xml": (xml_chunks, "application/xml; charset=utf-8"),
    }
    if format in streams:
        chunks, content_type = streams[format]
        response = StreamingHttpResponse(
            chunks(rows, columns), content_type=content_type,
        )
        response["Content-Disposition"] = content_disposition_header(True, f"{filename}.{format}")
        return response

    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        write_xlsx(rows, columns, output, sheet_name=sheet_name)
        output.seek(0)
        return FileResponse(
            output, as_attachment=True, filename=f"{filename}.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception:
        output.close()
        raise
