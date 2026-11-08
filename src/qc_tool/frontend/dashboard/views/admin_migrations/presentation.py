"""Render native migration identities and retained operations without changing them."""

from qc_tool.frontend.dashboard.services.transfer_presentation import local_datetime

from .urls import migration_url


AREA_LABELS = {
    "accounts": "Accounts & access", "dashboard": "QC Tool data",
    "qc_database": "Database transfers", "admin": "Django administration",
    "auth": "Django permissions", "contenttypes": "Django content types", "sessions": "Django sessions",
}
STORAGE_LABELS = {"included": "Available", "empty": "No retained files found",
                  "partial": "Partially available", "unavailable": "Unavailable", "omitted": "Not selected"}


def migration_names(values):
    """Accept service plans and review receipts while preserving native identities."""
    rows = []
    for value in values or []:
        if isinstance(value, dict):
            parts = (value.get("app_label", value.get("app", "")), value.get("name", value.get("migration", "")))
        elif isinstance(value, (list, tuple)):
            parts = value[:2]
        else:
            parts = (value,)
        rows.append(".".join(str(part) for part in parts if part))
    return rows


def migration_rows(values):
    rows = []
    for value in values or []:
        if not isinstance(value, dict):
            continue
        app = value.get("app", value.get("app_label", ""))
        rows.append({**value, "identity": f"{app}.{value.get('name', '')}",
                     "area": AREA_LABELS.get(app, app), "atomic": value.get("atomic", True),
                     "recorded_local": local_datetime(value.get("applied_at"))})
    return rows


def operation_database(operation):
    return (((operation or {}).get("destination") or {}).get("database")
            or ((operation or {}).get("migration_result") or {}).get("target_database")
            or ((operation or {}).get("result") or {}).get("target_database"))


def operation_message(operation, active_database):
    if active_database and operation_database(operation) == active_database:
        return "This copy is the active database. The previous database and recovery evidence remain retained."
    return operation.get("message", "")


def present_operation(operation, active_database):
    active = bool(active_database and operation_database(operation) == active_database)
    label = "In use" if active else {
        "queued": "Queued", "running": "Preparing and checking copy", "completed": "Verified copy retained",
        "failed": "Stopped; copy retained", "recovery_required": "Needs recovery",
    }.get(operation.get("status"), "Needs review")
    return {**operation, "created_local": local_datetime(operation.get("created_at")),
            "status_label": label, "message": operation_message(operation, active_database),
            "url": migration_url(operation["id"])}


def present_review(review):
    return {**review, "pending_names": migration_names(review.get("pending")),
            "storage_areas": [{**area, "status_label": STORAGE_LABELS.get(area.get("status"), "Needs review")}
                              for area in review.get("storage_areas", [])]}


def initializes_history(overview, operation):
    if overview.get("database", {}).get("state") == "pending":
        return False
    return (overview.get("database", {}).get("state") == "legacy"
            or bool(((operation or {}).get("upgrade") or {}).get("initializes_history")))
