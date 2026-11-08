"""Bind an upgrade review to native backup, source schema and retained files."""

from qc_tool.database import selection
from qc_tool.database.policy import load_policy
from qc_tool.database.transfers import control, recovery_files, service as transfers
from qc_tool.database.transfers.contracts import digest
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.services.maintenance.state import read_status
from .backups import reviewed_backup
from .connections import inspect_migrations
from .storage import inventory


def build_review(backup_id):
    backup = reviewed_backup(backup_id)
    state, maintenance = selection.read_state(), read_status()
    database = state["active"]
    report = inspect_migrations(database)
    blockers = []
    if report["state"] not in {"legacy", "pending"}:
        blockers.append("This database has no supported pending upgrade. Matching databases need no migration; schema drift must be investigated.")
    if not maintenance["enabled"] or maintenance["phase"] != "ready":
        blockers.append("Enable maintenance and wait for every worker to acknowledge the pause before reviewing an upgrade.")
    if active_operation():
        blockers.append("Complete or recover the operation that currently owns maintenance.")
    # This is the same byte/row review used when creating this exact backup.
    native, _inventory, _entries, current_hash, _bytes, _config = transfers._native_snapshot(backup["selection"])
    if current_hash != backup.get("reviewed_hash"):
        blockers.append("The database, selected files or configuration changed since this backup. Create a fresh backup in this maintenance window.")
    files = inventory()
    source_files = control._application_snapshot(database, allow_legacy=True)
    policy = load_policy()
    non_atomic = [f"{item['app']}.{item['name']}" for item in report["pending"] if not item.get("atomic", True)]
    value = {"backup_id": backup_id, "backup_sha256": backup["package_sha256"],
             "source_database": database, "source_release": report["source_release"] or "managed history",
             "target_release": policy["release"], "revision": state["revision"],
             "generation": maintenance["generation"], "source_migration": report,
             "source_native": {"review_hash": native["review_hash"], "oid": native["source"]["oid"]},
             "source_files": source_files, "storage_hash": files["fingerprint"],
             "pending": report["pending"], "blockers": blockers,
             "warnings": [*files["warnings"], *source_files["warnings"],
                          *(["Non-atomic migrations can leave committed partial changes on the candidate: " + ", ".join(non_atomic)] if non_atomic else []),
                          "Remote objects, encryption keys and private runtime control state require a separate recovery copy.",
                          "Keep external database and storage writers stopped until the upgrade is finished."],
             "storage_summary": f"{files['files_count']} retained files ({files['byte_count']} bytes); all five components selected, available retained files inventoried.",
             "storage_areas": files["areas"], "storage_exclusions": list(recovery_files.EXCLUSIONS),
             "can_apply": not blockers}
    value["review_hash"] = digest(value)
    return value
