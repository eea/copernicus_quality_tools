"""Execute a verified native copy under the existing owned execution lease."""

from io import StringIO
import os

from qc_tool.database import migration_engine
from qc_tool.database.policy import load_policy
from qc_tool.database.transfers import postgres, service as transfers, store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.services.maintenance.operations import unpin_operation
from .connections import candidate_connection
from .evidence import receipt_path, record_completion, require_source_unchanged, verify_candidate
from .operations import present_operation
from .storage import pin_original_files


def _restore_copy(operation):
    operation.update(status="running", error="", message="Restoring and verifying the separate upgrade copy.", restore_started=True)
    store.save_operation(operation)
    verified = transfers._verified(operation)
    operation["result"] = postgres.restore(verified, operation["core_plan"]["target_fingerprint"],
                                           destination=operation["destination"]["database"])
    # SQL history changes retain this deployment's original physical file paths.
    pin_original_files(operation)


def _apply_installed_plan(operation):
    with candidate_connection(operation) as candidate:
        report = migration_engine.migration_status(candidate)
        source = operation["upgrade"]["source_migration"]
        # Restore already verifies native SQL/data. Bind execution to the copy's
        # fingerprint because PostgreSQL can re-render equivalent CHECK syntax.
        fields = ("state", "applied", "pending", "targets", "graph", "problems", "source_release")
        if any(report[key] != source[key] for key in fields):
            raise TransferError("The restored copy does not match the reviewed source migration contract.")
        # Durable intent precedes every migration transaction or recorder write.
        operation.update(migration_started=True, message="Applying the installed Django migration graph to the isolated copy.")
        store.save_operation(operation)
        return migration_engine.apply_candidate(candidate, operation_id=operation["id"],
            expected_plan_hash=report["plan_hash"], expected_source_fingerprint=report["source_fingerprint"], stdout=StringIO())


def run(operation):
    """Called only inside the existing execution lease and owned ready barrier."""
    try:
        transfers._runner_actor(operation)
        require_source_unchanged(operation)
        if os.path.lexists(receipt_path(operation)):
            verify_candidate(operation)
        else:
            if operation.get("migration_started"):
                raise TransferError("Migration execution was interrupted without a completion receipt. Automatic replay is unsafe. Inspect the isolated copy, or keep it and stop this upgrade before starting a fresh copy.")
            _restore_copy(operation)
            require_source_unchanged(operation)
            result = _apply_installed_plan(operation)
            require_source_unchanged(operation)
            record_completion(operation, result)
        operation.update(status="completed", error="", message="The upgraded copy is verified. Review and approve the database switch separately.",
                         migration_result={"target_database": operation["destination"]["database"], "release": load_policy()["release"]})
        store.save_operation(operation)
        unpin_operation(operation["id"])
        return present_operation(operation)
    except Exception as error:
        operation.update(status="recovery_required", safe_to_cancel=False,
                         error=str(error) if isinstance(error, TransferError) else "The isolated upgrade stopped. Inspect its retained evidence before retrying; source data was not replaced.",
                         message="Maintenance remains held. The source, candidate, backup and journals are retained.")
        store.save_operation(operation)
        raise TransferError(operation["error"]) from error
