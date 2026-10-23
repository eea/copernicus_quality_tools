"""Reviewed transfers with durable maintenance ownership and atomic SQL import.

HTTP requests only plan/enqueue. A dedicated management-command process runs
independently of the paused QC worker pool. The SQL receipt resolves a crash
between COMMIT and the filesystem journal; a lost runner never opens admission.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction
from django.utils.crypto import constant_time_compare

from qc_tool.database import selection as database_selection
from qc_tool.database.deployment import SchemaInitializer
from qc_tool.database.models import TransferReceipt
from qc_tool.frontend.accounts.authorization import AccountAccess
from qc_tool.frontend.dashboard.services.maintenance import advance
from qc_tool.frontend.dashboard.services.maintenance.barrier import ready_barrier
from qc_tool.frontend.dashboard.services.maintenance.state import MaintenanceError, file_lock, read_status
from qc_tool.frontend.dashboard.services.maintenance.operations import (
    active_operation, pin_operation, require_no_operation, unpin_operation,
)

from .archive import ArtifactSource, ArchiveLimits, inspect_archive, open_regular, write_archive
from .artifacts import collect_artifacts, plan_artifact_restore
from .contracts import digest, require_uuid, record_limit
from .errors import RecordLimitError, TransferError
from .records import (
    RESOURCE_FIELDS, apply_records, export_record_counts, export_records,
    plan_records, validate_records, verify_records,
)
from .plan_storage import public_result, verify_rebuilt_plan
from . import postgres, recovery_files, store

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "cancelled", "failed"}
RUNNER_START_GRACE_SECONDS = 10
_UNSET = object()


def _authorize(actor):
    if not AccountAccess.from_user(actor).is_administrator:
        raise TransferError("Only an active QC Tool administrator can manage database transfers.")


def _actor_identity(actor):
    alias = actor._state.db
    database = (connections[alias].settings_dict["NAME"] if alias and alias != "default"
                else database_selection.current_database())
    return {"actor_id": actor.pk, "actor_name": actor.get_username(), "actor_database": str(database)}


def _runner_actor(operation):
    """Bind a journal to its administrator's database, never to a reused ID."""
    active = database_selection.current_database()
    origin = operation.get("actor_database", active)
    if origin != active:
        state, maintenance = database_selection.read_state(), read_status()
        if not maintenance["enabled"] or state.get("maintenance_generation") != maintenance["generation"]:
            raise TransferError("Administrator access belongs to a previous database. Sign in on the active database before retrying.")
    alias = "default" if origin == active else database_selection.alias_for_database(origin)
    try:
        actor = get_user_model().objects.using(alias).get(pk=operation["actor_id"])
        if actor.get_username() != operation["actor_name"]:
            raise TransferError("The transfer administrator identity changed. Review the operation before retrying.")
        _authorize(actor)
        return actor
    except get_user_model().DoesNotExist as error:
        raise TransferError("The transfer administrator no longer exists. Sign in as an administrator and review recovery.") from error
    finally:
        if alias != "default":
            connections[alias].close()


def _active_import_actor(actor, *, for_update=False):
    """Portable import receipts must reference the verified active identity."""
    users = get_user_model().objects
    if for_update:
        users = users.select_for_update()
    try:
        active = users.get(username=actor.get_username())
        if not constant_time_compare(active.password, actor.password):
            raise get_user_model().DoesNotExist
        _authorize(active)
    except (get_user_model().DoesNotExist, TransferError) as error:
        raise TransferError("Sign in as an administrator on the active database before importing selective records.") from error
    return active


def _limits():
    return ArchiveLimits(**getattr(settings, "QC_TOOL_TRANSFER_ARCHIVE_LIMITS", {}))


def schema_readiness():
    """Read-only preflight for administrative transfer controls.

    Keep the inspector's concrete drift reason available to administrators so
    an unsupported target is actionable before an operation is staged/pinned.
    This function never initializes or changes an existing schema.
    """
    from .compatibility import CURRENT_CONTRACT_VERSION
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        SchemaInitializer(connection).check()
    except CommandError as error:
        return {"ready": False, "state": "drift", "checked_at": checked_at,
                "contract_version": CURRENT_CONTRACT_VERSION, "message": str(error)}
    except DatabaseError:
        logger.exception("The administrative transfer schema preflight could not inspect the database.")
        return {"ready": False, "state": "unavailable", "checked_at": checked_at, "contract_version": CURRENT_CONTRACT_VERSION,
                "message": "The database could not be inspected. Check database connectivity and run database check."}
    return {"ready": True, "state": "ready", "checked_at": checked_at,
            "contract_version": CURRENT_CONTRACT_VERSION, "message": "The database matches current models."}


def database_availability():
    """Native recovery must remain available when model readiness has drifted."""
    result = postgres.availability()
    return {"ready": result.get("available", False), "message": result.get("reason", ""),
            "can_create_restore_database": result.get("can_create_restore", False),
            "restore_reason": result.get("restore_reason", ""),
            "restore_database": getattr(settings, "QC_TOOL_RESTORE_DATABASE", "")}


def database_control_status(actor):
    from .control import status
    return status(actor)


def activation_preview(operation_id, actor):
    from .control import preview
    return preview(operation_id, actor)


def activate_database(operation_id, actor, **confirmation):
    from .control import activate
    return activate(operation_id, actor, **confirmation)


def rollback_database(actor, **confirmation):
    from .control import rollback
    return rollback(actor, **confirmation)


def validate_resume_database(actor):
    from .control import validate_resume
    return validate_resume(actor)


def _schema_ready():
    readiness = schema_readiness()
    if not readiness["ready"]:
        raise TransferError("The current database is not ready for record transfer. " + readiness["message"])


def _require_space(path, byte_count):
    path = Path(path)
    while not path.exists():
        path = path.parent
    reserve = getattr(settings, "QC_TOOL_TRANSFER_MIN_FREE_BYTES", 512 * 1024**2)
    if shutil.disk_usage(path).free < byte_count + reserve:
        raise TransferError("Transfer storage has insufficient free space including its configured reserve. Free space before retrying.")


def _restore_space(restore):
    volumes = {}
    for entry in restore.create:
        path = Path(restore.roots[entry["root"]])
        while not path.exists():
            path = path.parent
        device = path.stat().st_dev
        if device not in volumes:
            volumes[device] = [path, 0]
        volumes[device][1] += entry["size"]
    for path, byte_count in volumes.values():
        _require_space(path, byte_count)


@contextmanager
def _ready_guard(generation=None, *, owner=None):
    try:
        with ready_barrier(generation, owner=owner) as state:
            yield state
    except MaintenanceError as error:
        raise TransferError(str(error)) from error


def _selection(selection):
    if not isinstance(selection, dict) or set(selection) not in ({"profile", "user_ids"}, {"profile", "user_ids", "include_files"}):
        raise TransferError("Choose a supported export scope.")
    profile, ids = selection["profile"], selection["user_ids"]
    if not isinstance(profile, str) or profile not in {"accounts", "application", "database"} or not isinstance(ids, list) or any(type(pk) is not int or pk <= 0 for pk in ids):
        raise TransferError("Choose a supported export scope and account identities.")
    if len(set(ids)) != len(ids) or (profile in {"application", "database"} and ids):
        raise TransferError("Application exports require the complete connected dataset.")
    include_files = selection.get("include_files", profile == "application")
    if type(include_files) is not bool:
        raise TransferError("Choose whether to include files in the export.")
    return {"profile": profile, "user_ids": sorted(ids), "include_files": include_files if profile != "accounts" else False}


def _snapshot(selection):
    from .compatibility import producer_metadata

    payload = export_records(selection["profile"], selection["user_ids"] or None,
                             semantic_contract=True,
                             **({"include_unreferenced_accounts": False} if selection["profile"] == "application" else {}))
    inventory = collect_artifacts(payload, include_files=selection["include_files"])
    inventory = replace(inventory, storage={**inventory.storage, "compatibility": producer_metadata(selection["profile"])})
    files, byte_count = [], 0
    for source in inventory.sources:
        hasher, size = hashlib.sha256(), 0
        with open_regular(source.path, storage_root=source.storage_root) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                byte_count += len(chunk)
                if size > _limits().max_member_bytes or byte_count > _limits().max_total_bytes:
                    raise TransferError("The selected files exceed the configured transfer limits.")
                hasher.update(chunk)
        files.append({"root": source.root, "key": source.key, "size": size, "sha256": hasher.hexdigest()})
    stable_payload = {key: value for key, value in payload.items() if key != "created_at"}
    review_hash = digest({"records": stable_payload, "files": files,
                          "directories": inventory.directories, "storage": inventory.storage})
    return payload, inventory, review_hash, byte_count, files


def _file_reference_counts(storage):
    items = (storage.get("references") or {}).get("items", [])
    if "recovery_files" in storage:
        return None
    if not isinstance(items, list):
        return None
    counts = {"total": len(items), "included": 0, "not_included": 0,
              "missing": 0, "unverified": 0, "remote": 0}
    for item in items:
        counts["included" if item.get("inclusion") == "included" else "not_included"] += 1
        availability = item.get("availability")
        if availability in {"missing", "unavailable", "missing_at_source", "different"}:
            counts["missing"] += 1
        elif availability in {"unverified", "legacy_unknown", "unknown"}:
            counts["unverified"] += 1
        elif availability in {"remote", "external"}:
            counts["remote"] += 1
    return counts


def _native_snapshot(selection):
    native = postgres.preview()
    if not selection["include_files"]:
        return native, None, [], native["review_hash"], 0
    inventory, entries, file_hash, byte_count = recovery_files.snapshot(limits=_limits())
    review_hash = digest({"database": native["review_hash"], "files": file_hash})
    return native, inventory, entries, review_hash, byte_count


def _export_capacity(byte_count):
    """Report known file-capacity blockers before pinning a long export."""
    blockers = []
    if byte_count > _limits().max_archive_bytes:
        blockers.append("The selected file contents exceed the configured package size limit. Choose records only or have an operator increase the transfer limit and backup capacity.")
    try:
        _require_space(store._directory_path(), byte_count)
    except TransferError:
        blockers.append("Backup storage has insufficient free space for the selected files and its reserve. Choose records only or provide more backup storage before exporting files.")
    except OSError:
        blockers.append("Backup storage availability could not be checked. Check its mount and permissions before exporting.")
    return blockers


def _counts(payload):
    return {"accounts": len(payload["accounts"]), **{key: len(rows) for key, rows in payload["records"].items()}}


def _record_capacity(selection):
    counts = export_record_counts(selection["profile"], selection["user_ids"] or None,
                                  include_unreferenced_accounts=selection["profile"] != "application")
    return {"counts": counts, "total_records": sum(counts.values()), "record_limit": record_limit()}


def export_preview(selection, actor):
    _authorize(actor)
    selection = _selection(selection)
    with _ready_guard():
        if selection["profile"] == "database":
            native, inventory, entries, review_hash, byte_count = _native_snapshot(selection)
            return {**native, "review_hash": review_hash, "profile": "database", "selection": selection,
                    "blockers": _export_capacity(byte_count), "files_count": len(entries), "byte_count": byte_count,
                    "exclusions": list(recovery_files.EXCLUSIONS) if inventory else [
                        "Files outside PostgreSQL, deployment secrets and PostgreSQL cluster roles"],
                    "notes": ["Includes every database table and field, stored credentials, permissions and sessions."]
                             + (list(inventory.warnings) if inventory else [])}
        _schema_ready()
        capacity = _record_capacity(selection)
        if capacity["total_records"] > capacity["record_limit"]:
            error = RecordLimitError(capacity["total_records"], capacity["record_limit"])
            return {**capacity, "profile": selection["profile"], "selection": selection,
                    "capacity": {"code": "record_limit", "record_count": error.count, "record_limit": error.limit},
                    "review_hash": "", "blockers": [str(error)], "files_count": 0, "byte_count": 0,
                    "file_references": {}, "notes": [], "exclusions": []}
        payload, inventory, review_hash, byte_count, _files = _snapshot(selection)
    counts = _counts(payload)
    return {"selection": selection, "review_hash": review_hash, "counts": counts,
            "total_records": sum(counts.values()), "record_limit": capacity["record_limit"],
            "files_count": len(inventory.sources), "byte_count": byte_count, "blockers": _export_capacity(byte_count),
            "file_references": _file_reference_counts(inventory.storage),
            "exclusions": ["Passwords, API keys, sessions and infrastructure secrets", "Automatic roles and product grants"],
            "notes": list(inventory.warnings) + list(inventory.external_requirements)}


def _new(kind, actor, **values):
    operation_id = str(uuid4())
    store.operation_dir(operation_id, create=True)
    value = {"version": 1, "id": operation_id, "kind": kind, **_actor_identity(actor),
             "status": "staged", "created_at": store.now(),
             "updated_at": store.now(), "message": "", "error": "", "result": {}, "plan": None,
             **values}
    return store.save_operation(value)


def _launch(operation):
    path = store.operation_dir(operation["id"])
    try:
        with open(path / "runner.log", "ab", opener=lambda name, flags: os.open(name, flags | os.O_NOFOLLOW, 0o600)) as log:
            subprocess.Popen([sys.executable, "-m", "qc_tool.frontend.manage", "data_transfer", "run", operation["id"]],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, start_new_session=True)
    except OSError as error:
        operation.update(status="recovery_required", safe_to_cancel=not (
                             operation.get("files_started", False) or operation.get("restore_started", False)),
                         error="The transfer runner could not start. Retry this operation; maintenance remains held.")
        store.save_operation(operation)
        raise TransferError(operation["error"]) from error


def _queue(prepare, generation):
    # Refresh positive worker acknowledgements immediately before pinning.
    try:
        advance(expected_generation=generation)
    except MaintenanceError as error:
        raise TransferError(str(error)) from error
    with store.execution_lock(), _ready_guard(generation):
        # Prepare only after admission succeeds, under the same locks as the pin.
        # Rejected exports therefore leave no journal, and a second request
        # cannot enqueue a stale copy of an already queued import.
        operation = prepare()
        operation.update(status="queued", generation=generation, queued_at=store.now(),
                         message="Waiting for the dedicated transfer runner.", error="")
        store.save_operation(operation)
        pin_operation(operation["id"], operation["kind"], generation)
    _launch(operation)
    return _public(operation)


def create_export(selection, actor, reviewed_hash, generation):
    _authorize(actor)
    selection = _selection(selection)
    if not isinstance(reviewed_hash, str) or len(reviewed_hash) != 64:
        raise TransferError("Preview and review the export before starting it.")
    def prepare():
        if selection["profile"] != "database":
            capacity = _record_capacity(selection)
            if capacity["total_records"] > capacity["record_limit"]:
                raise RecordLimitError(capacity["total_records"], capacity["record_limit"])
        return _new("export", actor, selection=selection, profile=selection["profile"],
                    reviewed_hash=reviewed_hash, package_id=str(uuid4()))

    return _queue(prepare, generation)


def stage_import(upload, actor, *, include_files=None):
    _authorize(actor)
    if include_files is not None and type(include_files) is not bool:
        raise TransferError("Choose whether to import the package's files.")
    with store.execution_lock():
        operation = _new("import", actor)
        path = store.operation_dir(operation["id"]) / "package.zip"
        try:
            size = 0
            with open(path, "xb", opener=lambda name, flags: os.open(name, flags | os.O_NOFOLLOW, 0o600)) as handle:
                for chunk in upload.chunks():
                    size += len(chunk)
                    if size > _limits().max_archive_bytes:
                        raise TransferError("The uploaded package exceeds the configured transfer limit.")
                    _require_space(path.parent, len(chunk))
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            store.sync_directory(path.parent)
            verified = inspect_archive(path, limits=_limits())
            _validate_manifest(verified, validate_payload=False)
            from .compatibility import inspect_compatibility
            compatibility = inspect_compatibility(verified)
            if verified.manifest["profile"] == "database":
                postgres.inspect_native(verified)
            elif compatibility["supported"]:
                validate_records(verified.records)
                if verified.manifest["profile"] == "application":
                    from .artifacts import _validate_package_artifacts
                    _validate_package_artifacts(verified)
            selected_files = (verified.manifest["profile"] == "application" or bool(verified.storage.get("recovery_files"))) if include_files is None else include_files
            operation.update(profile=verified.manifest["profile"], package_sha256=verified.package_sha256,
                             package_id=verified.manifest["package_id"], compatibility=compatibility,
                             include_files=selected_files if verified.manifest["profile"] != "accounts" else False,
                             message="Package staged. No records have been changed.")
            store.save_operation(operation)
        except Exception as error:
            path.unlink(missing_ok=True)
            operation.update(status="failed", error=str(error) if isinstance(error, TransferError) else "The package could not be staged safely.")
            store.save_operation(operation)
            if isinstance(error, TransferError):
                raise
            raise TransferError(operation["error"]) from error
    return _public(operation)


def _validate_manifest(verified, *, validate_payload=True):
    manifest = verified.manifest
    if set(manifest) != {"format", "version", "package_id", "created_at", "profile", "contract"} or type(manifest["version"]) is not int or manifest["version"] != 1:
        raise TransferError("Unsupported application transfer manifest.")
    require_uuid(manifest["package_id"], "Package identity")
    if not isinstance(manifest["profile"], str) or manifest["profile"] not in {"accounts", "application", "database"}:
        raise TransferError("Unsupported application transfer profile.")
    if manifest["profile"] == "database":
        if (manifest["format"] != "qc-tool-postgresql" or manifest["contract"] != "postgresql-native-v1"
                or not isinstance(verified.records, dict)
                or manifest["created_at"] != verified.records.get("created_at")):
            raise TransferError("Unsupported PostgreSQL backup manifest.")
        return
    if manifest["format"] != "qc-tool-data" or not isinstance(verified.records, dict):
        raise TransferError("Unsupported application transfer manifest.")
    if validate_payload:
        from .compatibility import inspect_compatibility
        if inspect_compatibility(verified)["supported"]:
            validate_records(verified.records)
    if (manifest["profile"] != verified.records.get("profile") or manifest["contract"] != verified.records.get("contract")
            or manifest["created_at"] != verified.records.get("created_at")):
        raise TransferError("The package manifest and records disagree.")


def _verified(operation):
    verified = inspect_archive(store.operation_dir(operation["id"]) / "package.zip", limits=_limits())
    _validate_manifest(verified)
    if verified.package_sha256 != operation["package_sha256"] or verified.manifest["package_id"] != operation["package_id"]:
        raise TransferError("The staged package changed. Upload the original package again.")
    return verified


def _make_plan(operation, verified, mappings, resolutions=None, account_choices=None):
    from .compatibility import inspect_compatibility
    compatibility = inspect_compatibility(verified)
    if not compatibility["supported"]:
        public = {"profile": operation["profile"], "compatibility": compatibility,
                  "can_apply": False, "blockers": [compatibility["message"]], "warnings": [],
                  "counts": {}, "account_mappings": [], "exclusions": [],
                  "target_label": "Current database", "confirmation_text": "", "target_scope": "No records will be changed",
                  "package_sha256": operation["package_sha256"], "include_files": operation.get("include_files", True)}
        public["plan_hash"] = digest(public)
        return public, {"mappings": {}}, None
    if operation["profile"] == "database":
        if account_choices is not None:
            raise TransferError("User selection and profile replacement apply only to user-account packages.")
        if mappings is not None and (not isinstance(mappings, dict) or mappings):
            raise TransferError("Full database restores preserve identities and do not accept account mappings.")
        postgres.inspect_native(verified)
        destination = (operation.get("destination") or {}).get("database")
        if not destination and not getattr(settings, "QC_TOOL_RESTORE_DATABASE", ""):
            native = {"can_apply": False, "blockers": [], "warnings": [],
                      "target_label": "Fresh restore destination", "confirmation_text": "",
                      "target_fingerprint": None, "counts": verified.records.get("counts", {}),
                      "source_details": verified.records.get("source_details", {})}
        else:
            native = postgres.plan_restore(verified, destination=destination)
        restore = recovery_files.plan_restore(verified, journal_path=store.operation_dir(operation["id"]) / "files.json",
                                              include_files=operation.get("include_files", False))
        _restore_space(restore)
        public = {**native, "profile": "database", "compatibility": compatibility,
                  "include_files": operation.get("include_files", False), "storage": restore.summary,
                  "package_sha256": operation["package_sha256"], "account_mappings": [],
                  "exclusions": list(recovery_files.EXCLUSIONS) if verified.storage.get("recovery_files") else [
                      "Files outside PostgreSQL and deployment secrets require separate restoration."],
                  "target_scope": "Separate empty database; the running database remains unchanged"}
        public["plan_hash"] = digest({"package": operation["package_sha256"], "review": public})
        return public, {"mappings": {}, "target_fingerprint": public.get("target_fingerprint")}, restore
    if operation["profile"] == "application" and not operation.get("include_files", True):
        from .artifacts import without_payloads
        verified = without_payloads(verified)
    if mappings is None:
        mappings = {}
    if not isinstance(mappings, dict):
        raise TransferError("Account mappings must explicitly name source keys and valid target account IDs.")
    mappings = {key: value for key, value in mappings.items() if value is not None and value != "new"}
    if resolutions is None:
        resolutions = (operation.get("core_plan") or {}).get("resolutions", {})
    if account_choices is None:
        account_choices = (operation.get("core_plan") or {}).get("account_choices")
    core = plan_records(verified.records, mappings, resolutions, account_choices=account_choices)
    delivery_files, file_conflicts = [], []
    selected = verified
    if core.get("mode") == "additive":
        from .artifacts import additive_archive, inspect_delivery_files, inspect_retained_artifact_conflicts
        inspection = inspect_delivery_files(verified)
        delivery_files = inspection["files"]
        for conflict in inspection["conflicts"]:
            source_key = conflict["key"].split(":", 1)[1]
            if core["actions"]["deliveries"].get(source_key) == "skip":
                continue
            from .merge import _conflict
            source = next(row for row in verified.records["records"]["deliveries"] if str(row["id"]) == source_key)
            row = _conflict(verified.records, "deliveries", source, conflict["reason"])
            file_conflicts.append(row)
            core["blockers"].append(f"Delivery {source['filename']}: {conflict['reason']}")
            previous = core["actions"]["deliveries"].get(source_key)
            if previous in {"create", "reuse"}:
                core["actions"]["deliveries"][source_key] = "blocked"
                for summary in core["resource_summary"]:
                    if summary["resource"] == "deliveries":
                        summary[previous] -= 1
                        summary["blocked"] += 1
        existing_keys = {row["key"] for row in core["record_conflicts"]}
        core["record_conflicts"].extend(row for row in file_conflicts if row["key"] not in existing_keys)
        selected = additive_archive(verified, core["included"])
        for conflict in inspect_retained_artifact_conflicts(selected):
            resource, source_key = conflict["resource"], conflict["source_key"]
            from .merge import _conflict
            model = RESOURCE_FIELDS[resource][0]
            source = next(row for row in verified.records["records"][resource]
                          if str(row[model._meta.pk.attname]) == source_key)
            if not any(row["key"] == conflict["key"] for row in core["record_conflicts"]):
                core["record_conflicts"].append(_conflict(verified.records, resource, source, conflict["reason"]))
            core["blockers"].append(conflict["reason"])
            previous = core["actions"][resource].get(source_key)
            if previous in {"create", "reuse"}:
                core["actions"][resource][source_key] = "blocked"
                for summary in core["resource_summary"]:
                    if summary["resource"] == resource:
                        summary[previous] -= 1
                        summary["blocked"] += 1
    restore = None
    warnings = []
    if not core["blockers"]:
        try:
            restore = plan_artifact_restore(selected, journal_path=store.operation_dir(operation["id"]) / "files.json")
            _restore_space(restore)
            warnings = list(getattr(restore, "warnings", ()))
        except TransferError as error:
            core["blockers"].append(str(error))
    if verified.records.get("records", {}).get("remote_sources"):
        warnings.append("Remote S3 objects and credentials are excluded. Provision and verify destination access separately before resuming affected deliveries.")
    blockers = list(core["blockers"])
    receipt = TransferReceipt.objects.filter(package_id=operation["package_id"]).first()
    if receipt:
        blockers.append("This package has already been imported. Its committed receipt prevents duplicate imports.")
    label = "{} / {}".format(connection.vendor, Path(str(database_selection.current_database())).name)
    source_accounts = {row["key"]: row for row in verified.records["accounts"]}
    public = {"profile": operation["profile"], "counts": core["counts"], "blockers": blockers,
              "compatibility": compatibility, "include_files": operation.get("include_files", True),
              "file_references": _file_reference_counts(selected.storage),
              "warnings": warnings,
              "exclusions": core["exclusions"], "package_sha256": operation["package_sha256"],
              "storage": restore.summary if restore else {},
              "mode": core.get("mode", "accounts"),
              "resource_summary": core.get("resource_summary", []),
              "record_conflicts": core.get("record_conflicts", []),
              "resolutions": core.get("resolutions", {}), "delivery_files": delivery_files,
              "account_choices": core.get("account_choices", {}), "account_summary": core.get("account_summary", {}),
              "target_label": label, "target_scope": "Add records to the current database; existing records and review decisions stay unchanged" if operation["profile"] == "application" else "Create inactive users, reuse identities or update reviewed names and email; ownership and access remain unchanged",
              "confirmation_text": label, "can_apply": not blockers,
              "account_mappings": [{"source_id": row["source_key"], "username": row["username"],
                                    "email": source_accounts[row["source_key"]]["email"],
                                    "first_name": source_accounts[row["source_key"]]["first_name"],
                                    "last_name": source_accounts[row["source_key"]]["last_name"],
                                    **{key: row[key] for key in ("selected", "disposition", "choices", "candidate_targets", "differences") if key in row},
                                    "target_id": row["target_user_id"], "requires_mapping": row["action"] == "blocked",
                                    "blocker": next((message.removeprefix(f"Account {row['username']}: ")
                                                     for message in core["blockers"]
                                                     if message.startswith(f"Account {row['username']}: ")), ""),
                                    "grant_proposals": row["grant_proposals"], "role_proposals": row["role_proposals"]}
                                   for row in core["accounts"]]}
    public["plan_hash"] = digest({"core": core, "review": {key: value for key, value in public.items() if key not in {"storage", "delivery_files"}}, "storage": verified.storage,
                                  "entries": list(verified.entries), "directories": list(verified.directories)})
    return public, core, restore


def prepare_restore_destination(operation_id, actor):
    """Create only a fresh, server-owned destination after an explicit UI action."""
    _authorize(actor)
    with store.execution_lock(), _ready_guard():
        operation = store.read_operation(operation_id)
        if (operation["kind"] != "import" or operation.get("profile") != "database"
                or operation["status"] not in {"staged", "planned"}):
            raise TransferError("Choose a staged full database backup before preparing its destination.")
        verified = _verified(operation)
        operation["destination"] = postgres.prepare_restore_target(verified, operation_id)
        plan, core, _restore = _make_plan(operation, verified, {})
        operation.update(status="planned", plan=plan, core_plan=core,
                         message="Fresh destination prepared. Review the backup and confirm the restore.")
        store.save_operation(operation)
        return _public(operation)


def plan_import(operation_id, actor, mappings=None, resolutions=None, *, account_choices=None,
                expected_plan_hash=None):
    _authorize(actor)
    with store.execution_lock(), _ready_guard():
        operation = store.read_operation(operation_id)
        if (expected_plan_hash is not None
                and expected_plan_hash != (operation.get("plan") or {}).get("plan_hash")):
            raise TransferError("The import review changed. Reload it before saving your choices.")
        if operation.get("profile") != "database":
            _schema_ready()
            _active_import_actor(actor)
        if operation["kind"] != "import" or operation["status"] not in {"staged", "planned"}:
            raise TransferError("Only a staged package can be planned.")
        verified = _verified(operation)
        if account_choices is not None and operation.get("profile") == "accounts":
            if not isinstance(account_choices, dict):
                raise TransferError("User choices must name only accounts in the uploaded package.")
            account_choices = {**(operation.get("core_plan") or {}).get("account_choices", {}), **account_choices}
        if mappings is None:
            mappings = (operation.get("core_plan") or {}).get("mappings", {})
        elif account_choices is None and operation.get("profile") == "accounts":
            # Legacy mapping forms own the complete selection when explicitly
            # submitted. New user-choice forms preserve their own saved choices.
            account_choices = {}
        plan, core, _restore = _make_plan(operation, verified, mappings, resolutions, account_choices)
        operation.update(status="planned", plan=plan, core_plan=core, message="Read-only validation finished. Review this exact plan before importing.")
        store.save_operation(operation)
        return plan


def start_import(operation_id, actor, plan_hash, generation, confirmed_scope=False):
    _authorize(actor)
    def prepare():
        operation = store.read_operation(operation_id)
        if (operation["kind"] != "import" or operation["status"] != "planned" or not confirmed_scope
                or not operation.get("plan") or operation["plan"]["plan_hash"] != plan_hash
                or not operation["plan"]["can_apply"]):
            raise TransferError("Review and confirm a valid import plan before applying it.")
        # Catch changes already visible at confirmation before creating a
        # maintenance pin or launching a runner. The runner repeats these checks
        # to catch changes after admission, immediately before applying records.
        if operation.get("profile") != "database":
            _schema_ready()
            _active_import_actor(actor)
        verified = _verified(operation)
        current, core, _restore = _make_plan(operation, verified, operation["core_plan"]["mappings"])
        if current["plan_hash"] != operation["plan"]["plan_hash"] or not current["can_apply"]:
            raise TransferError("The destination or package changed. Recheck the destination before importing.")
        verify_rebuilt_plan(operation["core_plan"], core)
        # Record the confirming actor, independent of who staged the archive.
        operation.update(_actor_identity(actor))
        return operation
    return _queue(prepare, generation)


def _public(operation, *, pin=_UNSET, execution_busy=None):
    if pin is _UNSET:
        try:
            pin = active_operation()
        except MaintenanceError as error:
            raise TransferError(str(error)) from error
    owned = bool(pin and pin["operation_id"] == operation["id"])
    if execution_busy is None:
        execution_busy = store.execution_active() if owned else False
    runner_active = owned and execution_busy
    recoverable = owned and not runner_active and operation["status"] in {"queued", "running", "recovery_required"} | TERMINAL
    if recoverable and operation["status"] in {"queued", "running"}:
        # Popen returns before the child acquires its execution lock. Do not
        # describe a healthy child starting up as an interrupted operation.
        try:
            queued_at = datetime.fromisoformat(operation.get("queued_at") or operation["updated_at"])
            recoverable = (datetime.now(timezone.utc) - queued_at).total_seconds() >= RUNNER_START_GRACE_SECONDS
        except (KeyError, TypeError, ValueError):
            recoverable = False
    public = {key: value for key, value in operation.items() if key not in {"core_plan", "version", "actor_id"}}
    public["result"] = public_result(public.get("result"))
    return public | {
        "downloadable": operation["kind"] == "export" and operation["status"] == "completed",
        "maintenance_owned": owned, "runner_active": runner_active, "recoverable": recoverable,
        "cancellable": not runner_active and operation["status"] not in {"completed", "cancelled"} and (
            operation["kind"] == "export" or operation.get("safe_to_cancel", False)
            or (operation["status"] in {"queued", "staged", "planned", "failed"}
                and not operation.get("files_started", False) and not operation.get("restore_started", False)))}


def get_operation(operation_id, actor):
    _authorize(actor)
    return _public(store.read_operation(operation_id))


def list_operations(actor):
    _authorize(actor)
    try:
        pin = active_operation()
    except MaintenanceError as error:
        raise TransferError(str(error)) from error
    execution_busy = store.execution_active() if pin else False
    values = []
    for path in store.directory().iterdir():
        if path.is_dir() and not path.is_symlink():
            try:
                values.append(_public(store.read_operation(path.name), pin=pin, execution_busy=execution_busy))
            except TransferError:
                continue
    return sorted(values, key=lambda value: value["created_at"], reverse=True)[:50]


def download_operation(operation_id, actor):
    _authorize(actor)
    operation = store.read_operation(operation_id)
    original_import = operation["kind"] == "import" and operation.get("package_sha256") and operation["status"] != "cancelled"
    if not original_import and (operation["kind"] != "export" or operation["status"] != "completed"):
        raise TransferError("This export is not ready to download.")
    path = store.operation_dir(operation_id) / "package.zip"
    with open_regular(path) as source:
        handle = os.fdopen(os.dup(source.fileno()), "rb")
    return handle, {"filename": "qc-tool-{}-{}.zip".format(operation["profile"], operation["id"])}


def _begin_artifact_restore(operation):
    # A completed rollback proves only the previous attempt was safe to cancel.
    # Revoke that evidence durably before every new filesystem publication,
    # including receipt recovery, so process death cannot retain a stale permit.
    operation.update(files_started=True, safe_to_cancel=False)
    store.save_operation(operation)


def _restore_archive(verified, operation):
    if operation.get("profile") == "application" and not operation.get("include_files", True):
        from .artifacts import without_payloads
        verified = without_payloads(verified)
    core = operation.get("core_plan") or {}
    if core.get("mode") == "additive":
        from .artifacts import additive_archive
        return additive_archive(verified, core["included"])
    return verified


def run_operation(operation_id):
    """Execute/recover one pinned operation. Safe to retry after process death."""
    with store.execution_lock():
        operation = store.read_operation(operation_id)
        with _ready_guard(operation.get("generation"), owner=operation_id):
            if operation.get("profile") == "database":
                return _run_database_operation(operation)
            # A completed journal written before unpinning needs only cleanup.
            if operation["status"] in TERMINAL:
                if operation["kind"] == "import" and operation["status"] == "completed":
                    verified = _verified(operation)
                    receipt = TransferReceipt.objects.get(operation_id=operation_id)
                    if receipt.package_sha256 != operation["package_sha256"] or str(receipt.package_id) != operation["package_id"] or receipt.plan_sha256 != operation["plan"]["plan_hash"]:
                        raise TransferError("The committed receipt differs from the transfer journal; keep maintenance enabled.")
                    restore = plan_artifact_restore(_restore_archive(verified, operation), journal_path=store.operation_dir(operation_id) / "files.json")
                    _begin_artifact_restore(operation)
                    restore.apply(rollback_on_error=False)
                    verify_records(verified.records, receipt.summary)
                unpin_operation(operation_id)
                return _public(operation)
            operation.update(status="running", message="Validating the pinned package and database.", error="")
            store.save_operation(operation)
            committed = False
            database_attempted = False
            restore = None
            try:
                _schema_ready()
                actor = _runner_actor(operation)
                if operation["kind"] == "export":
                    _run_export(operation)
                else:
                    actor = _active_import_actor(actor)
                    verified = _verified(operation)
                    receipt = TransferReceipt.objects.filter(package_id=operation["package_id"]).first()
                    if receipt:
                        if str(receipt.operation_id) != operation_id or receipt.package_sha256 != operation["package_sha256"] or receipt.plan_sha256 != operation["plan"]["plan_hash"]:
                            raise TransferError("A different import receipt owns this package. Operator recovery is required.")
                        committed = True
                        # Recovery checks bytes and activation again, never inserts twice.
                        restore = plan_artifact_restore(_restore_archive(verified, operation), journal_path=store.operation_dir(operation_id) / "files.json")
                        _begin_artifact_restore(operation)
                        restore.apply(rollback_on_error=False)
                        operation["result"] = receipt.summary
                    else:
                        plan, core, restore = _make_plan(operation, verified, operation["core_plan"]["mappings"])
                        if plan["plan_hash"] != operation["plan"]["plan_hash"] or plan["blockers"]:
                            raise TransferError("The target or reviewed plan changed. Cancel and review a new import plan.")
                        verify_rebuilt_plan(operation["core_plan"], core)
                        # Publish immutable bytes first. Failure leaves only owned,
                        # exact files reusable on retry; never overwrite or delete.
                        _begin_artifact_restore(operation)
                        restore.apply()
                        database_attempted = True
                        with transaction.atomic():
                            if connection.vendor == "postgresql":
                                with connection.cursor() as cursor:
                                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                            actor = _active_import_actor(actor, for_update=True)
                            result = apply_records(verified.records, core, actor=actor)
                            if operation["profile"] == "application":
                                from .artifact_references import receipt_references
                                selected = _restore_archive(verified, operation)
                                references = receipt_references(selected, result)
                                if references is not None:
                                    result["artifact_references"] = references
                                result["file_references"] = _file_reference_counts(selected.storage)
                            TransferReceipt.objects.create(package_id=operation["package_id"],
                                package_sha256=operation["package_sha256"], operation_id=operation_id,
                                plan_sha256=plan["plan_hash"], profile=operation["profile"], actor=actor,
                                actor_name=actor.get_username(), summary=result)
                        committed = True
                        operation["result"] = result
                    verify_records(verified.records, operation["result"])
                operation.update(status="completed", message="Transfer completed. Maintenance remains enabled; review the result before resuming QC Tool.", error="")
                store.save_operation(operation)
                unpin_operation(operation_id)
            except Exception as error:
                logger.exception("Database transfer %s stopped (%s).", operation_id, type(error).__name__)
                safe_to_cancel = not operation.get("files_started", False)
                commit_unknown = False
                if database_attempted and not committed:
                    try:
                        committed = TransferReceipt.objects.filter(operation_id=operation_id).exists()
                    except Exception:
                        # COMMIT acknowledgements can be lost. Never remove files
                        # unless SQL positively confirms no committed receipt.
                        commit_unknown = True
                if restore is not None and not committed and not commit_unknown:
                    try:
                        restore.rollback()
                        safe_to_cancel = True
                    except Exception:
                        logger.exception("Transfer %s retained files during rollback.", operation_id)
                        safe_to_cancel = False
                # Files may already be published or SQL committed. Retain pin on
                # every runner error; retry uses exact bytes + durable receipt.
                operation.update(status="recovery_required", error=str(error) if isinstance(error, TransferError) else "The transfer stopped unexpectedly. Operator recovery is required; see the private runner log.",
                                 message="Maintenance remains held. Retry this operation, or cancel only after reviewing its state.",
                                 committed=committed, commit_unknown=commit_unknown,
                                 safe_to_cancel=safe_to_cancel and not committed and not commit_unknown)
                store.save_operation(operation)
                raise TransferError(operation["error"]) from error
        return _public(operation)


def _run_database_operation(operation):
    """Reuse the durable runner without importing SQL into the live database.

    A native archive can contain arbitrary SQL. Only an explicitly confirmed
    administrator operation reaches this path, against the reviewed empty
    destination. Recovery verifies that destination instead of using receipts
    in the live application database or guessing that a lost COMMIT failed.
    """
    try:
        if operation["status"] in {"cancelled", "failed"}:
            unpin_operation(operation["id"])
            return _public(operation)
        _runner_actor(operation)
        if operation["status"] == "completed":
            if operation["kind"] == "import":
                verified = _verified(operation)
                operation["result"] = postgres.verify_restore(
                    verified, operation["core_plan"]["target_fingerprint"],
                    destination=(operation.get("destination") or {}).get("database"),
                )
                _apply_native_files(verified, operation)
            unpin_operation(operation["id"])
            return _public(operation)
        operation.update(status="running", error="", message="Checking the complete PostgreSQL backup.")
        store.save_operation(operation)
        if operation["kind"] == "export":
            _run_database_export(operation)
        else:
            verified = _verified(operation)
            if not operation.get("restore_started"):
                current, _core, _restore = _make_plan(operation, verified, {})
                if current["plan_hash"] != operation["plan"]["plan_hash"] or not current["can_apply"]:
                    raise TransferError("The restore destination changed. Cancel and review a new restore plan.")
            # Revoke earlier rollback evidence before every attempt, including
            # recovery, before the separate database transaction can begin.
            operation.update(restore_started=True, safe_to_cancel=False)
            store.save_operation(operation)
            operation["result"] = postgres.restore(
                verified, operation["core_plan"]["target_fingerprint"],
                destination=(operation.get("destination") or {}).get("database"),
            )
            _apply_native_files(verified, operation)
        operation.update(status="completed", error="",
                         message=("Complete PostgreSQL backup created. Maintenance remains enabled."
                                  if operation["kind"] == "export" else
                                  "The separate database was restored and verified. The running database was not replaced. Maintenance remains enabled."))
        store.save_operation(operation)
        unpin_operation(operation["id"])
    except Exception as error:
        # Do not log tool output, connection parameters or archive SQL.
        logger.error("Native database transfer %s stopped (%s).", operation["id"], type(error).__name__)
        safe_to_cancel = not operation.get("restore_started", False)
        if not safe_to_cancel:
            try:
                target = postgres.plan_restore(_verified(operation), destination=(operation.get("destination") or {}).get("database"))
                safe_to_cancel = (target.get("can_apply", False) and
                                  target.get("target_fingerprint") == operation["core_plan"]["target_fingerprint"])
            except Exception:
                # An unreachable or occupied target is never evidence that an
                # uncertain transaction rolled back. Preserve its pin/journal.
                pass
        operation.update(status="recovery_required", safe_to_cancel=safe_to_cancel,
                         error=str(error) if isinstance(error, TransferError) else
                         "The PostgreSQL operation stopped. Recover it to verify the separate destination; maintenance remains held.")
        store.save_operation(operation)
        raise TransferError(operation["error"]) from error
    return _public(operation)


def _apply_native_files(verified, operation):
    from .storage_pins import pin_restore_files
    restore = recovery_files.plan_restore(verified,
        journal_path=store.operation_dir(operation["id"]) / "files.json",
        include_files=operation.get("include_files", False))
    _restore_space(restore)
    pin_restore_files(operation, restore)
    _begin_artifact_restore(operation)
    restore.apply(rollback_on_error=False)
    operation["result"]["storage"] = restore.summary
    operation["result"]["include_files"] = operation.get("include_files", False)


def _run_database_export(operation):
    directory = store.operation_dir(operation["id"])
    dump = directory / "database.dump"
    temporary = directory / "package.partial"
    dump.unlink(missing_ok=True)
    temporary.unlink(missing_ok=True)
    try:
        from .compatibility import producer_metadata
        selection = _selection(operation["selection"])
        inventory, entries, file_hash, byte_count = (None, [], None, 0)
        if selection["include_files"]:
            inventory, entries, file_hash, byte_count = recovery_files.snapshot(limits=_limits())
        metadata = postgres.dump_to(dump)
        review_hash = digest({"database": metadata["review_hash"], "files": file_hash}) if inventory else metadata["review_hash"]
        if review_hash != operation["reviewed_hash"]:
            raise TransferError("The database changed since review. Cancel and review the backup again.")
        _require_space(directory, dump.stat().st_size + byte_count)
        manifest = {"format": "qc-tool-postgresql", "version": 1, "profile": "database",
                    "package_id": operation["package_id"], "created_at": metadata["created_at"],
                    "contract": "postgresql-native-v1"}
        checksum = write_archive(temporary, manifest, metadata,
            (ArtifactSource("database", "archive.dump", dump), *(inventory.sources if inventory else ())),
            directories=inventory.directories if inventory else (),
            storage={**(inventory.storage if inventory else {}), "compatibility": producer_metadata("database")},
            expected_artifacts=[{"root": "database", "key": "archive.dump", "sha256": metadata["dump_sha256"],
                                 "size": metadata["dump_bytes"]}, *entries], limits=_limits())
        os.replace(temporary, directory / "package.zip")
        store.sync_directory(directory)
        operation.update(package_sha256=checksum,
                         result={"counts": metadata.get("counts", {}),
                                 "include_files": selection["include_files"], "files_count": len(entries),
                                 "warnings": ["Contains stored credentials. Keep this backup private.",
                                              *list(inventory.warnings if inventory else ()),
                                              *(list(recovery_files.EXCLUSIONS) if inventory else [
                                                  "Files outside PostgreSQL and deployment secrets require separate backups."])]})
    finally:
        dump.unlink(missing_ok=True)


def _run_export(operation):
    payload, inventory, review_hash, byte_count, files = _snapshot(operation["selection"])
    if review_hash != operation["reviewed_hash"]:
        raise TransferError("The export contents changed since review. Cancel and preview the selection again.")
    if payload["profile"] == "application":
        # Namespace allocation happens only after the administrator's reviewed
        # export starts. Read-only previews and source bytes remain untouched.
        from .provenance import ensure_namespace
        ensure_namespace()
        # Release the reviewed graph before rebuilding it with its durable
        # namespace; retaining both copies doubles memory for large catalogs.
        del payload, inventory, files
        payload, inventory, _review_hash, byte_count, files = _snapshot(operation["selection"])
    path = store.operation_dir(operation["id"]) / "package.zip"
    temporary = path.with_suffix(".partial")
    temporary.unlink(missing_ok=True)
    _require_space(path.parent, byte_count)
    manifest = {"format": "qc-tool-data", "version": 1, "package_id": operation["package_id"],
                "created_at": payload["created_at"], "profile": payload["profile"], "contract": payload["contract"]}
    sha = write_archive(temporary, manifest, payload, inventory.sources,
                        directories=inventory.directories, storage=inventory.storage, limits=_limits(), expected_artifacts=files)
    os.replace(temporary, path)
    store.sync_directory(path.parent)
    operation.update(package_sha256=sha, result={"counts": _counts(payload), "warnings": list(inventory.warnings),
                                               "include_files": operation["selection"]["include_files"],
                                               "file_references": _file_reference_counts(inventory.storage),
                                               "external_requirements": list(inventory.external_requirements)})


def _discard_package(operation_id):
    """Remove only private package payloads after cancellation is proven safe.

    Audit/recovery journals remain available. Persist the unlink before marking
    cancellation or releasing a maintenance pin; a failed sync remains retryable.
    """
    directory = store.operation_dir(operation_id)
    try:
        for name in ("package.zip", "package.partial", "database.dump"):
            (directory / name).unlink(missing_ok=True)
        store.sync_directory(directory)
    except OSError as error:
        raise TransferError("The private package could not be discarded durably. Audit journals were kept; retry Discard before releasing maintenance.") from error


def recover_operation(operation_id, actor, action):
    _authorize(actor)
    with store.execution_lock():
        operation = store.read_operation(operation_id)
        if action == "retry":
            if operation["status"] not in {"queued", "running", "recovery_required"} | TERMINAL:
                raise TransferError("Only an interrupted pinned transfer can be retried.")
            generation = operation.get("generation")
            try:
                pin = active_operation()
            except MaintenanceError as error:
                raise TransferError(str(error)) from error
            if (type(generation) is not int or generation < 0 or not pin
                    or pin["operation_id"] != str(operation_id) or pin["generation"] != generation):
                raise TransferError("Only an interrupted transfer that still owns maintenance can be retried.")
            with _ready_guard(generation, owner=operation_id):
                operation.update(error="", message=("Recovery queued; the reviewed separate destination will be verified before another restore attempt."
                                                    if operation.get("profile") == "database" else
                                                    "Recovery queued; the SQL receipt prevents duplicate insertion."),
                                 recovered_by=actor.get_username(), **_actor_identity(actor),
                                 queued_at=store.now())
                if operation["status"] not in TERMINAL:
                    operation["status"] = "queued"
                store.save_operation(operation)
        elif action == "cancel":
            # Never undo a committed import or delete files with possible refs.
            never_started = (operation["status"] in {"staged", "planned", "failed", "cancelled"}
                             and "generation" not in operation and not operation.get("files_started", False))
            if operation["kind"] == "import" and operation.get("profile") == "database" and operation.get("restore_started"):
                # An uncertain restore can only be cancelled after positively
                # proving its reviewed target is still empty. A restored or
                # externally changed database requires verification/recovery.
                current = postgres.plan_restore(_verified(operation), destination=(operation.get("destination") or {}).get("database"))
                if (not current.get("can_apply") or current.get("target_fingerprint") != operation["core_plan"]["target_fingerprint"]):
                    raise TransferError("The separate restore target is occupied or changed. Recover and verify this restore before releasing maintenance.")
                operation["safe_to_cancel"] = True
            elif operation["kind"] == "import" and operation.get("profile") != "database" and not never_started:
                if not operation.get("package_id"):
                    raise TransferError("The import package identity is unavailable. Keep maintenance enabled and reconcile its audit journal.")
                try:
                    committed = TransferReceipt.objects.filter(package_id=operation["package_id"]).exists()
                except DatabaseError as error:
                    raise TransferError("The import's committed receipt cannot be checked. Keep maintenance enabled and check database readiness before retrying recovery.") from error
                if committed:
                    raise TransferError("This import has a committed receipt. Retry verification; committed imports cannot be cancelled.")
            with file_lock("control", blocking=False) as acquired:
                if not acquired:
                    raise TransferError("Another maintenance action is in progress.")
                pin = active_operation()
                if pin and pin["operation_id"] != str(operation_id):
                    raise TransferError("A different operation owns maintenance.")
                if operation["status"] == "completed":
                    raise TransferError("Completed transfers cannot be cancelled.")
                # Imports may leave exact unreferenced files. Keep admission
                # closed if publication began, until a successful retry verifies
                # ownership and restores consistent SQL/file state.
                if ((operation.get("status") in {"running", "recovery_required"} or operation.get("files_started", False) or operation.get("restore_started", False))
                        and operation["kind"] == "import"
                        and not operation.get("safe_to_cancel", False)):
                    raise TransferError("This import may have published files. Retry it to completion; an operator must reconcile any unrecoverable package before releasing maintenance.")
                _discard_package(operation_id)
                operation.update(status="cancelled", message="Transfer cancelled and private package discarded. Maintenance remains enabled.")
                store.save_operation(operation)
                if pin:
                    unpin_operation(operation_id)
        else:
            raise TransferError("Choose retry or cancel.")
    if action == "retry":
        _launch(operation)
    return _public(operation)
