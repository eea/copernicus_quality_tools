"""Public administrator upgrade API, backed by the shared transfer engine.

Preparation binds a reviewed backup to an operation-owned copy. Inspection,
execution evidence and recovery each have their own owner; no entry point moves
business storage or migrates the active serving database.
"""

from qc_tool.database.transfers import control, service as transfers, store
from qc_tool.database.transfers.errors import TransferError
from .evidence import verify_candidate
from .execution import run
from .operations import get_operation
from .overview import status
from .recovery import recover
from .review import build_review


def preview(backup_id, actor):
    transfers._authorize(actor)
    with transfers._ready_guard():
        return build_review(str(backup_id))


def start(backup_id, actor, review_hash, generation, revision):
    review = preview(backup_id, actor)
    if (not review["can_apply"] or review["review_hash"] != review_hash
            or review["generation"] != generation or review["revision"] != revision):
        raise TransferError("The upgrade review changed. Review the current database, backup and installed migrations again.")
    # Keep the complete recovery ZIP, but restore only its SQL. Existing shared
    # files are verified/pinned below, never planned as a storage import.
    staged = transfers.stage_import_path(store.package_path(backup_id), actor, include_files=False)
    operation_id = staged["id"]
    # Preparation is resumable and confined by the transfer ownership journal.
    transfers.prepare_restore_destination(operation_id, actor)
    def prepare():
        current = build_review(backup_id)
        if current["review_hash"] != review_hash or not current["can_apply"]:
            raise TransferError("The source changed while preparing its copy. Review a new upgrade; the prepared empty copy was retained.")
        operation = store.read_operation(operation_id)
        if operation.get("package_sha256") != current["backup_sha256"]:
            raise TransferError("The staged backup differs from the reviewed backup. Preserve the copies and review again.")
        operation["upgrade"] = current
        operation.update(transfers._actor_identity(actor))
        store.save_operation(operation)
        return operation
    return transfers._queue(prepare, generation)


def activation_preview(operation_id, actor):
    get_operation(operation_id, actor)
    return control.preview(operation_id, actor)


def activate(operation_id, actor, **confirmation):
    get_operation(operation_id, actor)
    return control.activate(operation_id, actor, **confirmation)
