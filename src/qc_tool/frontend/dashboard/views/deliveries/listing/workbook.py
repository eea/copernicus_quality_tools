"""Workbook construction for delivery exports."""

import io
import uuid

import openpyxl

from qc_tool.frontend.dashboard.services.exports import spreadsheet_cell_value


def delivery_workbook_bytes(rows):
    """Serialize projected delivery rows as an XLSX workbook."""

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Deliveries"

    if not rows:
        worksheet.append(["No data found"])
    else:
        headers = list(rows[0].keys())
        worksheet.append(headers)
        for row in rows:
            worksheet.append(
                [_workbook_value(row.get(column, "")) for column in headers]
            )

    for column in worksheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column)
        worksheet.column_dimensions[column[0].column_letter].width = min(
            max_length + 2,
            60,
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _workbook_value(value):
    if isinstance(value, uuid.UUID):
        value = str(value)
    return spreadsheet_cell_value(value)
