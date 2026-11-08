"""Recover held upgrades without replaying uncertain migration execution."""

import os

from qc_tool.database.transfers import service as transfers, store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation, unpin_operation
from .evidence import receipt_path, require_source_unchanged
from .operations import present_operation


def recover(operation_id, actor, action):
    transfers._authorize(actor)
    with store.execution_lock():
        operation = store.read_operation(operation_id)
        if not operation.get("upgrade"):
            raise TransferError("Choose a database migration operation.")
        pin = active_operation()
        if (not pin or pin["operation_id"] != operation_id
                or pin["generation"] != operation.get("generation")
                or operation["status"] not in {"queued", "running", "recovery_required", "completed"}):
            raise TransferError("Only an interrupted upgrade that still owns maintenance can be recovered.")
        with transfers._ready_guard(operation.get("generation"), owner=operation_id):
            transfers._runner_actor(operation)
            require_source_unchanged(operation)
            if action == "abandon":
                if operation["status"] == "completed" or os.path.lexists(receipt_path(operation)):
                    raise TransferError("A completed upgrade must be verified, not abandoned.")
                operation.update(status="failed", message="Upgrade stopped. Its copy, backup and audit evidence are retained; maintenance remains enabled.", error="")
                store.save_operation(operation)
                unpin_operation(operation_id)
                return present_operation(operation)
            if action != "retry":
                raise TransferError("Choose retry verification or keep the copy and stop the upgrade.")
            if operation.get("migration_started") and not os.path.lexists(receipt_path(operation)):
                raise TransferError("An uncertain migration is never automatically replayed. Inspect the candidate or keep it and stop this upgrade, then start a fresh copy.")
            operation.update(status="queued", error="", queued_at=store.now(), **transfers._actor_identity(actor))
            store.save_operation(operation)
    transfers._launch(operation)
    return present_operation(operation)
