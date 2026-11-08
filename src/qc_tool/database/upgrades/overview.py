"""Read-only administrator inventory for installed migration readiness."""

from django.db import connection

from qc_tool.database import selection
from qc_tool.database.policy import load_policy
from qc_tool.database.transfers import service as transfers, store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.services.maintenance.state import read_status
from .backups import full_storage_coverage
from .connections import inspect_migrations
from .operations import present_operation


def status(actor):
    transfers._authorize(actor)
    state, maintenance = selection.read_state(), read_status()
    try:
        report = inspect_migrations(state["active"], include_applied_history=True)
    except TransferError as error:
        # Journals and maintenance remain useful when the selected SQL copy is
        # unavailable. Keep recovery visible without claiming a valid schema.
        report = {"state": "unavailable", "source_release": None, "applied": [], "applied_history": [], "pending": [],
                  "problems": [str(error)]}
    backups, operations = [], []
    for operation in transfers.list_operations(actor, limit=None, include_storage=True):
        if operation.get("upgrade"):
            operations.append(present_operation(store.read_operation(operation["id"])))
        elif operation.get("kind") == "export" and operation.get("profile") == "database":
            scope = operation.get("selection", {})
            full = full_storage_coverage(scope)
            blockers = [] if full else ["All five business storage components are required."]
            if operation["status"] != "completed" or operation.get("package_release_requested_at"):
                blockers.append("This backup is incomplete or its local package was released.")
            backups.append({"id": operation["id"], "label": "PostgreSQL and retained files", "created_at": operation["created_at"],
                            "package_bytes": operation.get("stored_package_bytes"), "eligible": not blockers,
                            "coverage": "Database, specifications, boundaries, deliveries, artifacts and publications" if full else "Partial backup",
                            "blockers": blockers, "warnings": []})
    preparation_blockers = list(report["problems"])
    if connection.vendor != "postgresql":
        preparation_blockers.append("The Admin backup-and-copy upgrade workflow requires PostgreSQL. SQLite upgrades need an offline disposable-copy procedure.")
    if report["state"] not in {"legacy", "pending"}:
        preparation_blockers.append("There are no supported pending migrations to prepare." if report["state"] == "ready" else
                                    "Inspect the database schema and migration history before preparing an upgrade.")
    if not maintenance["enabled"] or maintenance["phase"] != "ready":
        preparation_blockers.append("Turn on maintenance and wait for every worker to acknowledge the pause.")
    if active_operation():
        preparation_blockers.append("Complete or recover the operation that owns maintenance before preparing another upgrade.")
    return {"installed_release": load_policy()["release"], "source_release": report["source_release"] or "managed history",
            "active_database": state["active"], "previous_database": state.get("previous"),
            "database": report, "maintenance": maintenance,
            "backups": backups, "operations": operations, "blockers": report["problems"],
            "can_prepare": not preparation_blockers, "preparation_blockers": list(dict.fromkeys(preparation_blockers))}
