"""Database-row projection for delivery-list consumers."""

from uuid import UUID
from types import SimpleNamespace

from django.urls import reverse

from qc_tool.frontend.dashboard.access import (
    delivery_action_capabilities, delivery_product_scope_matches,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    classify_delivery_status,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.workflows import (
    classify_delivery_workflow,
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
        delivery = SimpleNamespace(
            user_id=owner_id,
            product_ident=item.get("product_ident"),
            _scope_job_id=item.get("last_job_uuid"),
            _scope_job_product_ident=item.pop("action_job_product_ident", None),
            _scope_catalog_ident=item.pop("action_catalog_product_ident", None),
        )
        if include_capabilities:
            item.update(
                delivery_action_capabilities(account_access, delivery)
            )
        if "last_job_status" in item:
            item["delivery_status"] = classify_delivery_status(
                item["last_job_status"],
                item.get("date_submitted"),
                item.get("submission_review_state"),
                item.get("submission_publication_state"),
            ).value
            item["workflow_stage"] = classify_delivery_workflow(item["delivery_status"])
        submission_id = item.get("submission_id")
        if submission_id:
            # SQLite raw cursors return UUID hex strings; the public URL and
            # JSON contract use the same canonical UUID on both backends.
            submission_id = str(UUID(str(submission_id)))
            item["submission_id"] = submission_id
        item["submission_url"] = (
            reverse("submission_review", args=(submission_id,))
            if submission_id else ""
        )
        if "submission_id" in item:
            item["can_upload_correction"] = bool(
                submission_id
                and item.get("delivery_status") == "needs_correction"
                and account_access.user_id == owner_id
                and account_access.can_upload
                and delivery_product_scope_matches(account_access, delivery)
            )
            item["correction_upload_url"] = (
                "{}?correction_for={}".format(reverse("file_upload"), submission_id)
                if item["can_upload_correction"] else ""
            )
    return rows
