"""Route projection for delivery-list rows."""

from django.urls import reverse

from qc_tool.jobs import normalize_job_uuid


def add_delivery_links(rows):
    """Attach stable job history and result URLs to delivery rows in place."""

    for item in rows:
        item["job_history_url"] = reverse(
            "job_history",
            args=(item["id"],),
        )
        if item["last_job_uuid"]:
            # SQLite exposes compact text and PostgreSQL exposes UUID objects.
            item["last_job_uuid"] = normalize_job_uuid(
                item["last_job_uuid"]
            )
            item["job_result_url"] = reverse(
                "show_result",
                args=(item["last_job_uuid"],),
            )
        else:
            item["job_result_url"] = None
    return rows
