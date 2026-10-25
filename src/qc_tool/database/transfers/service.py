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
import stat
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

from .archive import (
    ArchiveLimits, artifact_path, canonical_json, compressed_sizes, inspect_archive,
    open_regular, write_archive, write_native_archive,
)
from .artifacts import collect_artifacts, plan_artifact_restore
from .contracts import digest, require_uuid, record_limit
from .components import EXPORT_COMPONENTS as BACKUP_COMPONENTS, COMPONENT_LABELS as BACKUP_LABELS
from .errors import RecordLimitError, TransferBusy, TransferError
from .records import (
    RESOURCE_FIELDS, apply_records, export_record_counts, export_records,
    plan_records, validate_records, verify_records,
)
from .plan_storage import public_result, verify_rebuilt_plan
from . import configuration, postgres, progress, recovery_files, store

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


def database_inventory(actor):
    """Read-only database names, sizes and the permitted management actions."""
    from .databases import inventory
    return inventory(actor)


def delete_restore_database(operation_id, actor, **confirmation):
    from .databases import delete
    return delete(operation_id, actor, **confirmation)


def database_details(database, actor):
    from .databases import details
    return details(database, actor)


def review_database_selection(database, actor):
    from .control import review_selection
    return review_selection(database, actor)


def select_database(database, actor, **confirmation):
    from .control import select
    return select(database, actor, **confirmation)


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
    if type(reserve) is not int or reserve < 0:
        raise TransferError("QC_TOOL_TRANSFER_MIN_FREE_BYTES must be a nonnegative integer.")
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
    if (not isinstance(selection, dict) or not {"profile", "user_ids"} <= set(selection)
            or set(selection) - {"profile", "user_ids", "include_files", "components"}):
        raise TransferError("Choose a supported export scope.")
    profile, ids = selection["profile"], selection["user_ids"]
    if not isinstance(profile, str) or profile not in {"accounts", "application", "database"} or not isinstance(ids, list) or any(type(pk) is not int or pk <= 0 for pk in ids):
        raise TransferError("Choose a supported export scope and account identities.")
    if len(set(ids)) != len(ids) or (profile in {"application", "database"} and ids):
        raise TransferError("Application exports require the complete connected dataset.")
    if "components" in selection:
        components = selection["components"]
        if (profile != "database" or not isinstance(components, list)
                or any(not isinstance(key, str) or key not in BACKUP_COMPONENTS for key in components)
                or len(set(components)) != len(components)):
            raise TransferError("Choose supported backup components without duplicates.")
        components = [key for key in BACKUP_COMPONENTS if key in components]
        return {"profile": "database", "user_ids": [], "components": components,
                "include_files": bool(set(components) & set(recovery_files.COMPONENTS))}
    include_files = selection.get("include_files", False)
    if type(include_files) is not bool:
        raise TransferError("Choose whether to include files in the export.")
    return {"profile": profile, "user_ids": sorted(ids), "include_files": include_files if profile != "accounts" else False}


def _snapshot(selection):
    from .archive import CompressionCounter
    from .compatibility import producer_metadata

    payload = export_records(selection["profile"], selection["user_ids"] or None,
                             semantic_contract=True,
                             **({"include_unreferenced_accounts": False} if selection["profile"] == "application" else {}))
    inventory = collect_artifacts(payload, include_files=selection["include_files"])
    inventory = replace(inventory, storage={**inventory.storage, "compatibility": producer_metadata(selection["profile"])})
    files, sources, byte_count = [], [], 0
    limits = _limits()
    for source in inventory.sources:
        hasher, size = hashlib.sha256(), 0
        counter = CompressionCounter()
        with open_regular(source.path, storage_root=source.storage_root) as handle:
            before = os.fstat(handle.fileno())
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                byte_count += len(chunk)
                if size > limits.max_member_bytes or byte_count > limits.max_total_bytes:
                    raise TransferError("The selected files exceed the configured transfer limits.")
                hasher.update(chunk)
                counter.write(chunk)
            after = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise TransferError("A selected file changed during backup review. Isolate external writers and retry.")
        checksum = hasher.hexdigest()
        sources.append(replace(source, compression=counter.finish(checksum, size, limits=limits)))
        files.append({"root": source.root, "key": source.key, "size": size, "sha256": checksum})
    stable_payload = {key: value for key, value in payload.items() if key != "created_at"}
    review_hash = digest({"records": stable_payload, "files": files,
                          "directories": inventory.directories, "storage": inventory.storage})
    return payload, replace(inventory, sources=tuple(sources)), review_hash, byte_count, files


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
    components = selection.get("components")
    native = postgres.preview(include_globals="postgresql_globals" in components) if components is not None else postgres.preview()
    if components is not None:
        inventory, entries, file_hash, byte_count = recovery_files.snapshot(
            limits=_limits(), components=[key for key in components if key in recovery_files.COMPONENTS])
        config = configuration.snapshot() if "deployment_configuration" in components else None
        review_hash = _backup_review_hash(native["review_hash"], file_hash, selection, config)
        return native, inventory, entries, review_hash, byte_count, config
    if not selection["include_files"]:
        return native, None, [], native["review_hash"], 0, None
    inventory, entries, file_hash, byte_count = recovery_files.snapshot(limits=_limits())
    review_hash = digest({"database": native["review_hash"], "files": file_hash})
    return native, inventory, entries, review_hash, byte_count, None


def _backup_review_hash(database_hash, file_hash, selection, config):
    return digest({"database": database_hash, "files": file_hash,
                   "components": selection["components"],
                   "configuration": config.fingerprint if config else None})


def _component_review(selection, native, inventory, entries, config):
    selected = selection.get("components", list(recovery_files.COMPONENTS) if selection["include_files"] else [])
    summary = ((inventory.storage.get("recovery_files") or {}).get("component_summary", {}) if inventory else {})
    rows = []
    for key in BACKUP_COMPONENTS:
        values = [entry for entry in entries if recovery_files.component_for(entry["root"], entry["key"]) == key]
        row = {"key": key, "label": BACKUP_LABELS[key], "selected": key in selected,
               "status": summary.get(key, {}).get("status", "included" if key in selected else "omitted"),
               "files_count": len(values), "byte_count": sum(entry["size"] for entry in values)}
        if key == "deployment_configuration" and config:
            row.update(files_count=config.files_count, byte_count=config.byte_count)
        elif key == "postgresql_globals" and key in selected:
            row.update(files_count=1, byte_count=native.get("globals_bytes", 0))
        rows.append(row)
    return rows


def _selection_metadata(rows):
    return canonical_json({"format": "qc-tool-backup-selection", "version": 1,
                           "selected_components": [row["key"] for row in rows if row["selected"]],
                           "omitted_components": [row["key"] for row in rows if not row["selected"]],
                           "components": rows})


def _export_capacity(byte_count):
    """Report known file-capacity blockers before pinning a long export."""
    blockers = []
    if byte_count > _limits().max_archive_bytes:
        blockers.append("The selected package contents exceed the configured package size limit. Deselect optional file sections, or increase the transfer limit with sufficient backup capacity.")
    try:
        _require_space(store._directory_path(), byte_count)
    except TransferError:
        blockers.append("Backup storage has insufficient free space for the selected package and its reserve. Deselect optional file sections, release completed export packages, or provide more backup storage.")
    except OSError:
        blockers.append("Backup storage availability could not be checked. Check its mount and permissions before exporting.")
    return blockers


def _compressed_file_bytes(entries, sources, *, format_version=1):
    sizes = compressed_sizes(sources, format_version=format_version)
    return sum(sizes.get(artifact_path(entry["root"], entry["key"], format_version=format_version), entry["size"])
               for entry in entries)


def _capacity_review(manifest, records, entries, *, directories=(), storage=None, database_bytes=None,
                     format_version=1, compressed_sources=()):
    """Size planned ZIP bytes separately from expanded recovery contents.

    PostgreSQL's physical database size includes indexes and bloat, whereas its
    custom dump is compressed. Never refuse a backup solely on that estimate.
    The streaming writer enforces actual package limits and free-space reserve.
    """
    from .archive import estimate_archive_size

    limits = _limits()
    compression = compressed_sizes(compressed_sources, format_version=format_version)
    sizes = estimate_archive_size(manifest, records, entries, directories=directories,
                                 storage=storage, limits=limits, validate_limits=False,
                                 format_version=format_version, compressed_sizes=compression)
    blockers = _export_capacity(sizes["archive_bytes"])
    if sizes["expanded_bytes"] > limits.max_total_bytes:
        blockers.append("The package's files and metadata exceed the expanded size limit.")
    if (sizes["records_bytes"] > min(limits.max_records_bytes, limits.max_member_bytes)
            or sizes["manifest_bytes"] > min(limits.max_manifest_bytes, limits.max_member_bytes)):
        blockers.append("The package metadata exceeds its configured limit. Use a native database backup or a smaller selection.")
    if any(entry["size"] > limits.max_member_bytes for entry in entries):
        blockers.append("A selected file exceeds the configured member size limit. Deselect that file section or increase QC_TOOL_TRANSFER_MAX_MEMBER_BYTES with sufficient storage.")
    if len(entries) + 2 > limits.max_members or sizes["central_directory_bytes"] > limits.max_central_directory_bytes:
        blockers.append("The package inventory exceeds its configured member or ZIP directory limit.")
    path = Path(store._directory_path())
    while not path.exists():
        path = path.parent
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        free = None
    reserve = getattr(settings, "QC_TOOL_TRANSFER_MIN_FREE_BYTES", 512 * 1024**2)
    estimated_package = sizes["archive_bytes"] + (database_bytes or 0)
    file_bytes = sum(entry["size"] for entry in entries)
    compressed_file_bytes = sum(compression.get(artifact_path(entry["root"], entry["key"],
                                    format_version=format_version), entry["size"]) for entry in entries)
    capacity = {"file_bytes": file_bytes, "compressed_file_bytes": compressed_file_bytes,
                "compression_saved_bytes": file_bytes - compressed_file_bytes,
                "records_bytes": sizes["records_bytes"], "estimated_database_bytes": database_bytes,
                "estimated_package_bytes": estimated_package,
                "required_free_bytes": estimated_package + reserve,
                "free_bytes": free, "reserve_bytes": reserve,
                "max_archive_bytes": limits.max_archive_bytes,
                "max_member_bytes": limits.max_member_bytes, "max_total_bytes": limits.max_total_bytes}
    notes = []
    if compression:
        notes.append("File compression preserves the original contents. ZIP size uses compressed files; restoring them requires space for the original contents.")
    if database_bytes is not None:
        notes.append("Database bytes are estimated from PostgreSQL storage, including indexes. The compressed dump can differ; actual limits and free space are checked while writing.")
        if estimated_package > limits.max_archive_bytes or (free is not None and estimated_package + reserve > free):
            notes.append("The estimated database backup may exceed available storage or the package limit. Use a larger private backup volume or review the configured limit before starting.")
    return blockers, capacity, notes


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
            native, inventory, entries, review_hash, byte_count, config = _native_snapshot(selection)
            manifest = {"format": "qc-tool-postgresql", "version": 1, "profile": "database",
                        "package_id": "0" * 36, "created_at": native["created_at"],
                        "contract": "postgresql-native-v2"}
            metadata = {key: value for key, value in native.items() if key not in {"estimated_dump_bytes", "section_estimates"}}
            metadata.update(dump_sha256="0" * 64, dump_bytes=0)
            additional = [{"root": "database", **entry} for entry in native.get("section_estimates", [])]
            additional.extend({"root": "database", "key": key, "size": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()}
                          for key, raw in (config.sections.items() if config else ()))
            if "postgresql_globals" in selection.get("components", []) and not any(item["key"] == "metadata/globals.sql" for item in additional):
                additional.append({"root": "database", "key": "metadata/globals.sql",
                                   "size": native.get("globals_bytes", 0), "sha256": "0" * 64})
            component_rows = _component_review(selection, native, inventory, entries, config)
            selection_bytes = _selection_metadata(component_rows)
            additional.append({"root": "database", "key": "metadata/selection.json",
                               "size": len(selection_bytes), "sha256": hashlib.sha256(selection_bytes).hexdigest()})
            metadata["sections"] = [{key: entry[key] for key in ("key", "sha256", "size")} for entry in additional]
            from .compatibility import producer_metadata
            blockers, storage_capacity, capacity_notes = _capacity_review(
                manifest, metadata,
                [{"root": "database", "key": "data/database.dump", "sha256": "0" * 64, "size": 0}, *additional, *entries],
                directories=inventory.directories if inventory else (),
                storage={**(inventory.storage if inventory else {}), "compatibility": producer_metadata("database")},
                database_bytes=native.get("estimated_dump_bytes"), format_version=2,
                compressed_sources=inventory.sources if inventory else ())
            return {**native, "review_hash": review_hash, "profile": "database", "selection": selection,
                    "blockers": blockers, "storage_capacity": storage_capacity,
                    "components": component_rows,
                    "files_count": len(entries), "byte_count": byte_count,
                    "exclusions": list(recovery_files.EXCLUSIONS) if inventory else [
                        "Files outside PostgreSQL, deployment secrets and PostgreSQL cluster roles"],
                    "notes": ["Includes every database table and field, stored credentials, permissions and sessions.", *capacity_notes]
                             + (list(inventory.warnings) if inventory else [])}
        _schema_ready()
        capacity = _record_capacity(selection)
        if capacity["total_records"] > capacity["record_limit"]:
            error = RecordLimitError(capacity["total_records"], capacity["record_limit"])
            return {**capacity, "profile": selection["profile"], "selection": selection,
                    "capacity": {"code": "record_limit", "record_count": error.count, "record_limit": error.limit},
                    "review_hash": "", "blockers": [str(error)], "files_count": 0, "byte_count": 0,
                    "file_references": {}, "notes": [], "exclusions": []}
        payload, inventory, review_hash, byte_count, files = _snapshot(selection)
        manifest = {"format": "qc-tool-data", "version": 1, "package_id": "0" * 36,
                    "created_at": payload["created_at"], "profile": payload["profile"], "contract": payload["contract"]}
        blockers, storage_capacity, capacity_notes = _capacity_review(
            manifest, payload, files, directories=inventory.directories, storage=inventory.storage,
            compressed_sources=inventory.sources)
    counts = _counts(payload)
    return {"selection": selection, "review_hash": review_hash, "counts": counts,
            "total_records": sum(counts.values()), "record_limit": capacity["record_limit"],
            "files_count": len(inventory.sources), "byte_count": byte_count, "blockers": blockers,
            "storage_capacity": storage_capacity,
            "file_references": _file_reference_counts(inventory.storage),
            "exclusions": ["Passwords, API keys, sessions and infrastructure secrets", "Automatic roles and product grants"],
            "notes": list(inventory.warnings) + list(inventory.external_requirements) + capacity_notes}


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


def stage_import_path(path, actor, *, include_files=None):
    """Operator-side staging avoids HTTP and multipart temporary copies.

    Keep the supplied original unchanged. The private staged copy receives the
    same bounded validation and subsequent explicit Admin review as an upload.
    """
    _authorize(actor)
    with open_regular(Path(path)) as source:
        size = os.fstat(source.fileno()).st_size
        if size > _limits().max_archive_bytes:
            raise TransferError("The supplied package exceeds the configured transfer limit.")
        _require_space(store._directory_path(), size)

        class LocalPackage:
            def chunks(self):
                yield from iter(lambda: source.read(1024 * 1024), b"")

        return stage_import(LocalPackage(), actor, include_files=include_files)


def _validate_manifest(verified, *, validate_payload=True):
    manifest = verified.manifest
    if set(manifest) != {"format", "version", "package_id", "created_at", "profile", "contract"} or type(manifest["version"]) is not int or manifest["version"] != 1:
        raise TransferError("Unsupported application transfer manifest.")
    require_uuid(manifest["package_id"], "Package identity")
    if not isinstance(manifest["profile"], str) or manifest["profile"] not in {"accounts", "application", "database"}:
        raise TransferError("Unsupported application transfer profile.")
    if manifest["profile"] == "database":
        if (manifest["format"] != "qc-tool-postgresql" or manifest["contract"] not in {"postgresql-native-v1", "postgresql-native-v2"}
                or not isinstance(verified.records, dict)
                or manifest["contract"] != "postgresql-native-v" + str(verified.records.get("version"))
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
    public["progress"] = progress.read(operation)
    return public | {
        "downloadable": operation["kind"] == "export" and operation["status"] == "completed"
                        and not operation.get("package_release_requested_at"),
        "releasable": operation["kind"] == "export" and operation["status"] == "completed"
                      and not owned and not operation.get("payload_released_at"),
        "maintenance_owned": owned, "runner_active": runner_active, "recoverable": recoverable,
        "cancellable": not runner_active and operation["status"] not in {"completed", "cancelled"} and (
            operation["kind"] == "export" or operation.get("safe_to_cancel", False)
            or (operation["status"] in {"queued", "staged", "planned", "failed"}
                and not operation.get("files_started", False) and not operation.get("restore_started", False)))}


def get_operation(operation_id, actor):
    _authorize(actor)
    return _public(store.read_operation(operation_id))


def list_operations(actor, *, limit=50, include_storage=False):
    """Read transfer journals, optionally inventorying their saved ZIP sizes.

    The default remains the recent audit feed. Storage management requests all
    journals so an older, large backup is never hidden behind that feed's limit.
    File inspection uses no-follow metadata only; archive contents are not read.
    """
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
                operation = _public(store.read_operation(path.name), pin=pin, execution_busy=execution_busy)
                if include_storage:
                    try:
                        package = (store.operation_dir(operation["id"]) / "package.zip").lstat()
                        if stat.S_ISREG(package.st_mode):
                            operation["stored_package_bytes"] = package.st_size
                        else:
                            operation.update(stored_package_bytes=None, storage_issue="Saved ZIP storage is unsafe.")
                    except FileNotFoundError:
                        operation["stored_package_bytes"] = 0
                    except OSError:
                        operation.update(stored_package_bytes=None, storage_issue="Saved ZIP size is unavailable.")
                values.append(operation)
            except TransferError:
                continue
    values.sort(key=lambda value: value["created_at"], reverse=True)
    return values if limit is None else values[:limit]


def backup_storage_capacity(actor):
    """Report the backup volume without exposing private storage paths."""
    _authorize(actor)
    reserve = getattr(settings, "QC_TOOL_TRANSFER_MIN_FREE_BYTES", 512 * 1024**2)
    if type(reserve) is not int or reserve < 0:
        raise TransferError("QC_TOOL_TRANSFER_MIN_FREE_BYTES must be a nonnegative integer.")
    try:
        capacity = shutil.disk_usage(store.directory())
    except OSError as error:
        raise TransferError("Backup volume capacity is unavailable.") from error
    return {"free_bytes": capacity.free, "total_bytes": capacity.total, "reserve_bytes": reserve}


def download_operation(operation_id, actor):
    _authorize(actor)
    operation = store.read_operation(operation_id)
    if operation.get("package_release_requested_at"):
        raise TransferError("This export package has been released from local storage. Its audit history remains available.")
    original_import = operation["kind"] == "import" and operation.get("package_sha256") and operation["status"] != "cancelled"
    if not original_import and (operation["kind"] != "export" or operation["status"] != "completed"):
        raise TransferError("This export is not ready to download.")
    path = store.operation_dir(operation_id) / "package.zip"
    with open_regular(path) as source:
        handle = os.fdopen(os.dup(source.fileno()), "rb")
    return handle, {"filename": "qc-tool-{}-{}.zip".format(operation["profile"], operation["id"]),
                    "sha256": operation.get("package_sha256"), "bytes": os.fstat(handle.fileno()).st_size}


def release_export_package(operation_id, actor):
    """Explicitly reclaim a completed export's payload, retaining all journals.

    Imports may still need their original package for receipt/file recovery or
    database activation. They never enter this cleanup path. Persist intent
    before unlinking so a crash cannot advertise a download that was removed.
    """
    _authorize(actor)
    try:
        with store.execution_lock(), file_lock("control", blocking=False) as acquired:
            if not acquired:
                raise TransferBusy("Another maintenance action is in progress.")
            operation = store.read_operation(operation_id)
            pin = active_operation()
            if operation["kind"] != "export" or operation["status"] != "completed":
                raise TransferError("Only a completed export package can be released. Imports and recovery packages must be retained.")
            if pin and pin["operation_id"] == operation["id"]:
                raise TransferError("Recover this transfer's maintenance pin before releasing its package.")
            if not operation.get("payload_released_at"):
                operation.setdefault("package_release_requested_at", store.now())
                operation["package_released_by"] = actor.get_username()
                store.save_operation(operation)
                _discard_package(operation_id)
                operation.update(payload_released_at=store.now(),
                                 message="Export package released from local storage. Audit history retained.")
                store.save_operation(operation)
    except MaintenanceError as error:
        raise TransferError(str(error)) from error
    return _public(operation)


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
    report = progress.Reporter(operation["id"])
    report("validating")
    _discard_export_scratch(operation["id"])
    directory = store.operation_dir(operation["id"])
    temporary = directory / "package.partial"
    temporary.unlink(missing_ok=True)
    from .compatibility import producer_metadata
    selection = _selection(operation["selection"])
    inventory, entries, file_hash, byte_count = (None, [], None, 0)
    components = selection.get("components")
    if components is not None:
        inventory, entries, file_hash, byte_count = recovery_files.snapshot(
            limits=_limits(), components=[key for key in components if key in recovery_files.COMPONENTS], report=report)
    elif selection["include_files"]:
        inventory, entries, file_hash, byte_count = recovery_files.snapshot(limits=_limits(), report=report)
    config = configuration.snapshot() if components and "deployment_configuration" in components else None
    _require_space(directory, _compressed_file_bytes(entries, inventory.sources if inventory else (), format_version=2))
    captured = {}

    def capture(output):
        metadata = (postgres.capture_stream(output, include_globals="postgresql_globals" in components, report=report)
                    if components is not None else postgres.capture_stream(output, report=report))
        review_hash = (_backup_review_hash(metadata["review_hash"], file_hash, selection, config)
                       if components is not None else
                       digest({"database": metadata["review_hash"], "files": file_hash}) if inventory else metadata["review_hash"])
        if review_hash != operation["reviewed_hash"]:
            raise TransferError("The database changed since review. Cancel and review the backup again.")
        if config:
            if configuration.snapshot().fingerprint != config.fingerprint:
                raise TransferError("Application configuration or credential files changed during backup. Review the selection again.")
            metadata.setdefault("_package_sections", {}).update(config.sections)
        if metadata["version"] == 2:
            rows = _component_review(selection, metadata, inventory, entries, config)
            metadata.setdefault("_package_sections", {})["metadata/selection.json"] = _selection_metadata(rows)
        captured.update({key: value for key, value in metadata.items() if key != "_package_sections"})
        manifest["created_at"] = metadata["created_at"]
        manifest["contract"] = "postgresql-native-v" + str(metadata["version"])
        return metadata

    manifest = {"format": "qc-tool-postgresql", "version": 1, "profile": "database",
                "package_id": operation["package_id"], "created_at": store.now(),
                "contract": "postgresql-native-v2"}
    checksum = write_native_archive(temporary, manifest, capture,
        inventory.sources if inventory else (),
        directories=inventory.directories if inventory else (),
        storage={**(inventory.storage if inventory else {}), "compatibility": producer_metadata("database")},
        expected_artifacts=entries, limits=_limits(),
        check_space=lambda growth: _require_space(directory, growth), report=report)
    report("publishing")
    os.replace(temporary, directory / "package.zip")
    store.sync_directory(directory)
    operation.update(package_sha256=checksum, package_bytes=(directory / "package.zip").stat().st_size,
                     source_details=captured.get("source_details", {}),
                     result={"counts": captured.get("counts", {}),
                             "include_files": selection["include_files"], "files_count": len(entries),
                             "components": selection.get("components"),
                             "warnings": ["Contains stored credentials. Keep this backup private.",
                                          *list(inventory.warnings if inventory else ()),
                                          *(list(recovery_files.EXCLUSIONS) if inventory else [
                                              "Files outside PostgreSQL and deployment secrets require separate backups."])]})


def _run_export(operation):
    report = progress.Reporter(operation["id"])
    report("validating")
    _discard_export_scratch(operation["id"])
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
    _require_space(path.parent, _compressed_file_bytes(files, inventory.sources))
    manifest = {"format": "qc-tool-data", "version": 1, "package_id": operation["package_id"],
                "created_at": payload["created_at"], "profile": payload["profile"], "contract": payload["contract"]}
    sha = write_archive(temporary, manifest, payload, inventory.sources,
                        directories=inventory.directories, storage=inventory.storage, limits=_limits(), expected_artifacts=files,
                        check_space=lambda growth: _require_space(path.parent, growth), report=report)
    report("publishing")
    os.replace(temporary, path)
    store.sync_directory(path.parent)
    operation.update(package_sha256=sha, package_bytes=path.stat().st_size,
                     result={"counts": _counts(payload), "warnings": list(inventory.warnings),
                                               "include_files": operation["selection"]["include_files"],
                                               "file_references": _file_reference_counts(inventory.storage),
                                               "external_requirements": list(inventory.external_requirements)})


def _discard_export_scratch(operation_id):
    """Reclaim killed writers' private scratch under the execution lock.

    These files are confined to one export's 0700 journal directory. Never
    sweep shared artifact roots, imports, or another operation's recovery data.
    """
    operation = store.read_operation(operation_id)
    if operation["kind"] != "export":
        return
    directory = store.operation_dir(operation_id)
    try:
        paths = [*directory.glob(".transfer-*.pending"), directory / "database.dump"]
        for path in paths:
            try:
                status = path.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
                raise TransferError("Export scratch storage is unsafe. Preserve the operation for operator inspection.")
            path.unlink()
        store.sync_directory(directory)
    except OSError as error:
        raise TransferError("Interrupted export scratch could not be reclaimed. Retry after checking private storage.") from error


def _discard_package(operation_id):
    """Remove only private package payloads after cancellation is proven safe.

    Audit/recovery journals remain available. Persist the unlink before marking
    cancellation or releasing a maintenance pin; a failed sync remains retryable.
    """
    directory = store.operation_dir(operation_id)
    try:
        _discard_export_scratch(operation_id)
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
                    raise TransferBusy("Another maintenance action is in progress.")
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
