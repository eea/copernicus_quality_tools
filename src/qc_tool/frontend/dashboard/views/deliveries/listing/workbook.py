"""The public delivery export schema, shared by JSON, CSV, XLSX, and XML."""

import io

from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    delivery_status_label,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.workflows import WORKFLOW_CONFIG
from qc_tool.frontend.dashboard.services.exports import ExportColumn
from qc_tool.frontend.dashboard.services.exports.tabular import write_xlsx


def _status_label(row):
    return delivery_status_label(
        row.get("delivery_status"), row.get("last_job_status"),
    )


# Newly added projection metadata, permissions and UI controls must not silently
# appear in downloads. Each field and label is an explicit public contract.
DELIVERY_EXPORT_COLUMNS = (
    ExportColumn("filename", "Delivery"),
    ExportColumn("product_description", "Product"),
    ExportColumn("date_uploaded", "Uploaded"),
    ExportColumn("last_job_status", "QC & review", _status_label),
    ExportColumn("size_bytes", "Size (bytes)"),
    ExportColumn("type", "Source"),
    ExportColumn("username", "Owner"),
    ExportColumn("id", "ID"),
    ExportColumn("product_ident", "Product identifier"),
    ExportColumn("product_unit_code", "Product unit"),
    ExportColumn("verified_product_unit_code", "Verified product unit"),
    ExportColumn("content_sha256", "SHA-256"),
    ExportColumn("date_submitted", "Submitted"),
    ExportColumn("last_job_uuid", "QC job ID"),
    ExportColumn("date_created", "QC created"),
    ExportColumn("date_started", "QC started"),
    ExportColumn("date_finished", "QC finished"),
    ExportColumn("delivery_status", "Delivery status", _status_label),
    ExportColumn("workflow_stage", "Workflow", lambda row: WORKFLOW_CONFIG.get(
        row.get("workflow_stage"), {},
    ).get("label", "")),
    ExportColumn("submission_id", "Submission ID"),
    ExportColumn("submission_review_state", "Review decision"),
    ExportColumn("review_notes", "Review comments"),
    ExportColumn("review_actor_username", "Reviewer"),
    ExportColumn("review_created_at", "Reviewed"),
)


def delivery_workbook_bytes(rows, columns=DELIVERY_EXPORT_COLUMNS):
    """Compatibility helper for consumers needing an in-memory XLSX."""

    buffer = io.BytesIO()
    write_xlsx(rows, columns, buffer, sheet_name="Deliveries")
    return buffer.getvalue()
