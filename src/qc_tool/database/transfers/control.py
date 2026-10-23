"""Reviewed database activation and reversible selection during maintenance.

Switching changes one private deployment pointer. It never copies, clears,
renames or drops a database. Native restoration and application readiness remain
separate checks, with the former serving database retained for rollback.
"""

import hashlib
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections
from django.utils.crypto import constant_time_compare

from qc_tool.database import selection
from qc_tool.database.deployment import SchemaInitializer
from qc_tool.frontend.accounts.authorization import AccountAccess
from qc_tool.frontend.dashboard.services.maintenance.state import read_status

from . import postgres, store
from .archive import _hash, open_regular
from .artifacts import collect_artifacts
from .contracts import digest
from .errors import TransferError
from .records import snapshot_current_application


def _service():
    # The public service is the facade; keep its admission and authorization
    # implementation shared without an import cycle at Django startup.
    from . import service
    return service


def _administrator(database, actor, username="", password="", *, required=False):
    """Check destination access without updating password hashes or SQL sessions."""
    alias = selection.alias_for_database(database)
    try:
        name = username or actor.get_username()
        try:
            lookup = "username__iexact" if settings.CONFIG["case_insensitive_usernames"] else "username"
            user = get_user_model().objects.using(alias).get(**{lookup: name})
        except (get_user_model().DoesNotExist, get_user_model().MultipleObjectsReturned):
            user = None
        allowed = bool(user and user.is_active and user.is_staff and user.has_usable_password()
                       and AccountAccess.from_user(user).is_administrator)
        if allowed:
            allowed = (check_password(password, user.password) if username or password else
                       constant_time_compare(user.password, actor.password))
        if not allowed:
            if required:
                raise TransferError("Verify an active administrator account on the destination before switching databases.")
            return None
        return {"username": user.get_username(),
                "auth_fingerprint": hashlib.sha256(user.get_session_auth_hash().encode()).hexdigest()}
    except DatabaseError as error:
        raise TransferError("Administrator access on the destination could not be checked. Maintenance remains on.") from error
    finally:
        if alias != "default":
            connections[alias].close()


def _application_snapshot(database):
    """Reuse the existing graph and artifact validators without changing data.

    The publication/specification validators check all available immutable evidence.
    Missing historical files remain explicit warnings and retained references;
    they do not make an otherwise valid model schema unselectable.
    Hash every retained file without copying it or applying archive-size limits
    to a database switch. Preserved timestamps never substitute for file bytes.
    """
    with selection.database_scope(database):
        try:
            SchemaInitializer(connection).check()
        except CommandError as error:
            raise TransferError(f"Database {database} does not match the installed models: {error}") from error
        payload = snapshot_current_application()
        inventory = collect_artifacts(payload, include_files=True)
        files = []
        for source in inventory.sources:
            with open_regular(source.path, storage_root=source.storage_root) as stream:
                info = os.fstat(stream.fileno())
                checksum, size = _hash(stream, info.st_size)
                final = os.fstat(stream.fileno())
                if (final.st_size, final.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                    raise TransferError("A retained file changed during destination review. Isolate storage writers and review again.")
            files.append({"root": source.root, "key": source.key, "size": size, "sha256": checksum,
                          "mtime_ns": info.st_mtime_ns, "inode": info.st_ino, "device": info.st_dev})
        fingerprint = digest({"records": {key: value for key, value in payload.items() if key != "created_at"},
                              "files": files, "directories": inventory.directories,
                              "storage": inventory.storage})
    return {"fingerprint": fingerprint, "files_count": len(files),
            "warnings": list(inventory.warnings) + list(inventory.external_requirements)}


def _native_snapshot(database):
    with selection.database_scope(database):
        value = postgres.preview()
    return {"review_hash": value["review_hash"], "oid": value["source"]["oid"]}


def _completed(operation_id):
    operation = store.read_operation(operation_id)
    if (operation.get("profile") != "database" or operation["kind"] != "import"
            or operation["status"] != "completed" or not operation.get("result", {}).get("verified")):
        raise TransferError("Complete and verify a full database restore before switching.")
    database = (operation.get("destination") or {}).get("database") or operation["result"].get("target_database")
    if not database:
        raise TransferError("This restore has no verified destination. Prepare and restore a fresh destination first.")
    return operation, database


def _preview(operation_id, actor):
    service = _service()
    state = selection.read_state()
    operation, database = _completed(operation_id)
    value = {"target_database": database, "source_database": state["active"],
             "revision": state["revision"], "requires_credentials": False, "blockers": [],
             "can_apply": False, "already_active": database == state["active"]}
    if value["already_active"]:
        return value
    verified = service._verified(operation)
    postgres.verify_restore(verified, operation["core_plan"]["target_fingerprint"], destination=database)
    target_files = _application_snapshot(database)
    source_files = _application_snapshot(state["active"])
    source_native = _native_snapshot(state["active"])
    access = _administrator(database, actor)
    value.update(can_apply=True, requires_credentials=access is None,
                 files_count=target_files["files_count"], warnings=target_files["warnings"])
    value["review_hash"] = digest({"operation": operation_id, "package": operation["package_sha256"],
                                  "state": state, "target_files": target_files,
                                  "source_files": source_files, "source_native": source_native})
    return value, {"target_files": target_files, "source_files": source_files,
                   "source_native": source_native, "operation": operation, "access": access}


def preview(operation_id, actor):
    service = _service()
    service._authorize(actor)
    with service._ready_guard():
        try:
            result = _preview(operation_id, actor)
            return result[0] if isinstance(result, tuple) else result
        except TransferError:
            raise
        except Exception as error:
            raise TransferError("The restored database and matching files are not ready to switch. Run the destination review and retain both databases.") from error


def _confirmation(state, generation, revision, name, destination_confirmation, confirmed_storage):
    if (type(revision) is not int or revision != state["revision"]
            or type(generation) is not int or generation != read_status()["generation"]):
        raise TransferError("The database or maintenance state changed. Reload and review the switch again.")
    if not confirmed_storage or destination_confirmation != name:
        raise TransferError("Confirm the exact destination and its matching files before switching databases.")


def activate(operation_id, actor, review_hash, generation, revision, destination_confirmation,
             confirmed_storage=False, username="", password=""):
    service = _service()
    service._authorize(actor)
    with store.execution_lock(), service._ready_guard(generation):
        state = selection.read_state()
        _operation, database = _completed(operation_id)
        _confirmation(state, generation, revision, database, destination_confirmation, confirmed_storage)
        reviewed = _preview(operation_id, actor)
        if not isinstance(reviewed, tuple):
            raise TransferError("This database is already active.")
        current, evidence = reviewed
        if not current["can_apply"] or current["review_hash"] != review_hash:
            raise TransferError("The destination, database records or matching files changed. Review the switch again.")
        access = _administrator(database, actor, username, password, required=True)
        value = {**state, "active": database, "previous": state["active"],
                 "revision": revision + 1, "operation_id": operation_id, "changed_at": store.now(),
                 "actor_name": actor.get_username(), "maintenance_generation": generation,
                 "activation": {"source_native": evidence["source_native"],
                                "source_files": evidence["source_files"], "access": access}}
        selection.write_state(value, expected_revision=revision)
        return value


def _rollback_blockers(state):
    if not state.get("previous"):
        return []
    maintenance = read_status()
    if (not maintenance["enabled"] or maintenance["generation"] != state.get("maintenance_generation")):
        return ["Rollback is available while maintenance stays on for this switch. New work may have changed data after reopening; both databases remain retained."]
    evidence = state.get("activation") or {}
    if not evidence.get("source_native") or not evidence.get("source_files"):
        return ["The retained copy needs a fresh verification before it can be selected. Both databases remain intact."]
    return []


def status(actor):
    _service()._authorize(actor)
    state = selection.read_state()
    blockers = _rollback_blockers(state)
    requires_credentials = False
    if state.get("previous") and not blockers:
        try:
            requires_credentials = _administrator(state["previous"], actor) is None
        except TransferError as error:
            blockers.append(str(error))
    return {"active_database": state["active"], "previous_database": state.get("previous"),
            "revision": state["revision"], "has_selection": bool(state["revision"]),
            "rollback_requires_credentials": requires_credentials, "rollback_blockers": blockers}


def rollback(actor, generation, revision, destination_confirmation, confirmed_storage=False,
             username="", password=""):
    service = _service()
    service._authorize(actor)
    with store.execution_lock(), service._ready_guard(generation):
        state = selection.read_state()
        previous = state.get("previous")
        if not previous or _rollback_blockers(state):
            raise TransferError("Rollback is unavailable after maintenance ends. Both databases were retained; review a new backup and restore instead.")
        _confirmation(state, generation, revision, previous, destination_confirmation, confirmed_storage)
        recorded = state.get("activation") or {}
        previous_native = _native_snapshot(previous)
        previous_files = _application_snapshot(previous)
        if (previous_native != recorded.get("source_native")
                or previous_files != recorded.get("source_files")):
            raise TransferError("The retained database or its matching files changed. Keep maintenance on and review both copies before switching.")
        access = _administrator(previous, actor, username, password, required=True)
        try:
            current_native = _native_snapshot(state["active"])
            current_files = _application_snapshot(state["active"])
        except Exception:
            # An unavailable newly selected DB must not prevent returning to a
            # positively verified original. Retain it, but do not claim another
            # reverse switch is safe without a fresh review of that copy.
            current_native = current_files = None
        value = {**state, "active": previous, "previous": state["active"],
                 "revision": revision + 1, "changed_at": store.now(), "actor_name": actor.get_username(),
                 "activation": {"source_native": current_native, "source_files": current_files, "access": access}}
        selection.write_state(value, expected_revision=revision)
        return value


def validate_resume(actor):
    """Do not reopen a selected database without verified administrator access."""
    service = _service()
    service._authorize(actor)
    state = selection.read_state()
    if (not state["revision"]
            or state.get("maintenance_generation") != read_status()["generation"]):
        return
    proof = (state.get("activation") or {}).get("access") or {}
    alias = selection.alias_for_database(state["active"])
    try:
        user = get_user_model().objects.using(alias).get(username=proof.get("username", ""))
        fingerprint = hashlib.sha256(user.get_session_auth_hash().encode()).hexdigest()
        if (not user.is_active or not user.is_staff or not user.has_usable_password()
                or not AccountAccess.from_user(user).is_administrator
                or not constant_time_compare(fingerprint, proof.get("auth_fingerprint", ""))):
            raise TransferError("Administrator access on the selected database changed. Keep maintenance on and review access before reopening.")
    except (DatabaseError, get_user_model().DoesNotExist) as error:
        raise TransferError("Administrator access on the selected database is unavailable. Keep maintenance on and use rollback before reopening.") from error
    finally:
        if alias != "default":
            connections[alias].close()
