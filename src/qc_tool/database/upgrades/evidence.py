"""Durable completion evidence and unchanged-source checks for recovery."""

from qc_tool.database import selection
from qc_tool.database.policy import load_policy
from qc_tool.database.transfers import control, store
from qc_tool.database.transfers.databases import managed_identity
from qc_tool.database.transfers.errors import TransferError
from .backups import package_identity
from .connections import inspect_migrations
from .storage import inventory


def require_source_unchanged(operation):
    review, state = operation["upgrade"], selection.read_state()
    if state["active"] != review["source_database"] or state["revision"] != review["revision"]:
        raise TransferError("Database selection changed. Preserve the upgrade evidence and inspect the selected database.")
    report = inspect_migrations(state["active"])
    if report["plan_hash"] != review["source_migration"]["plan_hash"]:
        raise TransferError("The installed graph or source schema/history changed. This upgrade must be reviewed again.")
    if control._native_snapshot(state["active"]) != review["source_native"]:
        raise TransferError("The source database changed after upgrade review. Preserve both databases and take a fresh backup.")
    if inventory()["fingerprint"] != review["storage_hash"]:
        raise TransferError("Retained business storage changed after upgrade review. Inspect the files before continuing.")


def receipt_path(operation):
    return store.operation_dir(operation["id"]) / "migration-completed.json"


def verify_candidate(operation):
    """Recheck a completion receipt without replaying migrations or old SQL."""
    require_source_unchanged(operation)
    checksum, _size = package_identity(operation)
    if checksum != operation["package_sha256"]:
        raise TransferError("The retained upgrade backup changed. Preserve the candidate and recovery evidence before switching.")
    receipt = store.read_json(receipt_path(operation))
    name = operation["destination"]["database"]
    identity = managed_identity(operation)
    if identity["database"] != name or identity["oid"] != (receipt.get("native") or {}).get("oid"):
        raise TransferError("The migrated candidate's physical identity or ownership changed. Preserve it before switching.")
    expected = {"operation_id": operation["id"], "package_sha256": operation["package_sha256"],
                "target_database": name, "target_release": load_policy()["release"]}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise TransferError("The migration completion evidence does not match this database copy or installed release.")
    report = inspect_migrations(name)
    if report["state"] != "ready" or report["plan_hash"] != receipt.get("migration_plan_hash"):
        raise TransferError("The candidate schema/history or installed migrations changed after completion.")
    if control._native_snapshot(name) != receipt.get("native"):
        raise TransferError("The candidate data or physical identity changed after migration. Review a fresh upgrade.")
    if control._application_snapshot(name) != receipt.get("application") or inventory()["fingerprint"] != receipt.get("storage_hash"):
        raise TransferError("The candidate file references or retained storage changed after migration.")
    return receipt


def record_completion(operation, result):
    """Write a receipt only after record references and retained files verify."""
    name = operation["destination"]["database"]
    application = control._application_snapshot(name)
    if set(application["warnings"]) - set(operation["upgrade"]["source_files"]["warnings"]):
        raise TransferError("The migrated database introduces unavailable file references. Inspect the isolated copy before selecting it.")
    receipt = {"version": 1, "operation_id": operation["id"], "package_sha256": operation["package_sha256"],
               "target_database": name, "target_release": load_policy()["release"],
               "migration_plan_hash": result["plan_hash"], "native": control._native_snapshot(name),
               "application": application, "storage_hash": inventory()["fingerprint"], "completed_at": store.now()}
    store.write_json(receipt_path(operation), receipt)
