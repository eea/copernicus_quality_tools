"""Public migration-operation projection with guarded recovery availability."""

import os

from qc_tool.database.transfers import service as transfers, store
from qc_tool.database.transfers.errors import TransferError
from .evidence import receipt_path


def present_operation(operation):
    value = transfers._public(operation)
    # Keep internal schema inventories and review evidence out of HTTP DTOs.
    upgrade = operation.get("upgrade", {})
    value["upgrade"] = {key: upgrade.get(key) for key in ("source_release", "target_release", "source_database")}
    value["upgrade"]["initializes_history"] = upgrade.get("source_migration", {}).get("state") == "legacy"
    value["cancellable"] = False
    receipt = os.path.lexists(receipt_path(operation))
    recoverable = value["recoverable"] and not value["runner_active"]
    uncertain = bool(operation.get("migration_started") and not receipt)
    value["can_retry"] = recoverable and not uncertain
    value["can_abandon"] = recoverable and operation["status"] != "completed" and not receipt
    value["recovery_reason"] = ("Migration execution began without a completion receipt. It cannot be replayed safely. "
                                "Keep the failed copy for inspection and stop this upgrade, then prepare a fresh copy."
                                if recoverable and uncertain else "")
    return value


def get_operation(operation_id, actor):
    transfers._authorize(actor)
    operation = store.read_operation(operation_id)
    if not operation.get("upgrade"):
        raise TransferError("Choose a database migration operation.")
    return present_operation(operation)
