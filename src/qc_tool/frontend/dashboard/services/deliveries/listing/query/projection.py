"""Database-row projection for delivery-list consumers."""

from qc_tool.frontend.dashboard.access import delivery_action_capabilities
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    classify_delivery_status,
)


def rows_from_cursor(cursor):
    """Map cursor tuples to dictionaries using the database column aliases."""

    header = [column[0] for column in cursor.description]
    return [dict(zip(header, row)) for row in cursor.fetchall()]


def project_delivery_rows(rows, account_access, include_capabilities):
    """Add stable presentation fields and remove the internal owner column."""

    for item in rows:
        item["type"] = "s3" if item["s3_id"] else "local"
        owner_id = item.pop("action_owner_id")
        if include_capabilities:
            item.update(
                delivery_action_capabilities(account_access, owner_id)
            )
        if "last_job_status" in item:
            item["delivery_status"] = classify_delivery_status(
                item["last_job_status"],
                item.get("date_submitted"),
            ).value
    return rows
