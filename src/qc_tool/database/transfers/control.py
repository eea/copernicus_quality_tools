"""Reviewed database activation and reversible selection during maintenance.

Switching changes one private deployment pointer. It never copies, clears,
renames or drops a database. Native restoration and application readiness remain
separate checks, with the former serving database retained for rollback.
"""

import hashlib
import os
from datetime import datetime

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
    deletion = store.operation_dir(operation_id) / "database-deletion.json"
    if deletion.exists() or deletion.is_symlink():
        raise TransferError("This database copy was selected for deletion. Use the database manager to finish or inspect its removal; it cannot be selected for use.")
    if (operation.get("profile") != "database" or operation["kind"] != "import"
            or operation["status"] != "completed" or not operation.get("result", {}).get("verified")):
        raise TransferError("Complete and verify a full database restore before switching.")
    database = (operation.get("destination") or {}).get("database") or operation["result"].get("target_database")
    if not database:
        raise TransferError("This restore has no verified destination. Prepare and restore a fresh destination first.")
    return operation, database


def _receipt_path(operation=None):
    return (store.operation_dir(operation["id"]) / "database-activation.json" if operation
            else store.directory() / "configured-database.json")


def _receipt(state, database, identity, operation=None):
    """Read prior explicit approval, bound to one deployment and physical copy."""
    path = _receipt_path(operation)
    if not path.exists() and not path.is_symlink():
        return None
    value = store.read_json(path, limit=16 * 1024)
    expected = {"version": 1, "configured": state["configured"], "database": database,
                "operation_id": operation["id"] if operation else None,
                "package_sha256": operation.get("package_sha256") if operation else None,
                "identity": identity}
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or set(value) != {*expected, "approved_at"}
            or any(value.get(key) != item for key, item in expected.items())):
        raise TransferError("This database's saved selection identity changed or belongs to another deployment. Keep both copies and ask the database administrator to inspect them.")
    try:
        if datetime.fromisoformat(value["approved_at"]).utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise TransferError("This database's saved selection approval is invalid. Operator inspection is required.") from None
    return value


def _remember(state, database, identity, operation=None):
    if _receipt(state, database, identity, operation) is None:
        # Approval is durable before pointer selection. A lost pointer-write
        # acknowledgement never erases the deliberately approved identity.
        store.write_json(_receipt_path(operation), {
            "version": 1, "configured": state["configured"], "database": database,
            "operation_id": operation["id"] if operation else None,
            "package_sha256": operation.get("package_sha256") if operation else None,
            "identity": identity, "approved_at": store.now(),
        })


def _configured_identity(state):
    from .databases import _cluster

    cluster = _cluster()
    name = state["configured"]["name"]
    row = next((row for row in cluster["databases"] if row["database"] == name), None)
    if row is None:
        raise TransferError("The configured original database is unavailable. Keep the active copy and inspect the PostgreSQL server.")
    return {"database": name, "oid": row["oid"], "owner_oid": row["owner_oid"],
            "host": cluster["params"].get("host", ""),
            "hostaddr": cluster["params"].get("hostaddr", ""),
            "port": cluster["params"].get("port", ""), "server_major": cluster["server_major"]}


def _remember_source(state, source_native):
    """Capture the configured source while its serving identity is proven."""
    if state["active"] != state["configured"]["name"]:
        return
    identity = _configured_identity(state)
    if identity["oid"] != source_native["oid"]:
        raise TransferError("The original database identity changed during review. Review the selection again.")
    _remember(state, state["active"], identity)


def can_review_selection(database, *, state=None, operation=None):
    """Cheap UI hint only; review revalidates physical identity and authority."""
    state = state or selection.read_state()
    if database == state["active"]:
        return False
    if database == state["configured"]["name"]:
        path = _receipt_path()
        return bool(path.exists() or path.is_symlink()
                    or (state.get("previous") == database
                        and ((state.get("activation") or {}).get("source_native") or {}).get("oid")))
    if operation:
        path = _receipt_path(operation)
        deletion = store.operation_dir(operation["id"]) / "database-deletion.json"
        return bool(operation.get("status") == "completed" and operation.get("result", {}).get("verified")
                    and (path.exists() or path.is_symlink())
                    and not (deletion.exists() or deletion.is_symlink()))
    return False


def _find_operation(database):
    from .databases import _operations

    operations, _warnings = _operations()
    return next((item for item in operations
                 if ((item.get("destination") or {}).get("database")
                     or item.get("result", {}).get("target_database")) == database), None)


def _selection_candidate(database, state, operation=None):
    from .databases import managed_identity

    if database == state["configured"]["name"]:
        identity = _configured_identity(state)
        receipt = _receipt(state, database, identity)
        if receipt is None:
            # Upgrade existing private selection evidence only while it still
            # identifies this exact retained original. Never adopt by name.
            prior = (state.get("activation") or {}).get("source_native") or {}
            if state.get("previous") != database or prior.get("oid") != identity["oid"]:
                raise TransferError("The original database has no trusted retained identity for selection. Restore a verified backup or ask the database administrator to inspect it.")
        return identity, None
    if operation is None:
        operation = _find_operation(database)
    if operation is None:
        raise TransferError("Select a previously reviewed QC Tool database copy. Other PostgreSQL databases cannot be selected from this interface.")
    operation, name = _completed(operation["id"])
    if name != database:
        raise TransferError("The selected restore copy changed. Reload the database manager.")
    identity = managed_identity(operation)
    if _receipt(state, database, identity, operation) is None:
        raise TransferError("Review this restored database from its import first. Its first activation must still match the original backup exactly.")
    return identity, operation


def _close_target_read_alias(database):
    """Release this request's completed authentication read before isolation."""
    alias = selection.alias_for_database(database)
    handle = connections[alias]
    if alias != "default" and handle.connection is not None:
        if handle.in_atomic_block or not handle.get_autocommit():
            raise TransferError("A local read transaction is still using the selected database. Finish that request before reviewing the switch.")
        handle.close()


def _isolate(database):
    # Run before ORM inspection opens the inactive target. Do not terminate
    # another client or assume a maintenance banner isolates external writers.
    _close_target_read_alias(database)
    params = postgres._params()
    with postgres._database({**params, "dbname": database}) as (handle, info):
        postgres._require_isolated_target(handle, info)


def _selection_preview(database, actor, state, operation=None):
    if database == state["active"]:
        return {"target_database": database, "source_database": state["active"], "revision": state["revision"],
                "already_active": True, "can_apply": False, "requires_credentials": False, "blockers": []}
    identity, operation = _selection_candidate(database, state, operation)
    _isolate(database)
    target_files = _application_snapshot(database)
    target_native = _native_snapshot(database)
    source_files = _application_snapshot(state["active"])
    source_native = _native_snapshot(state["active"])
    access = _administrator(database, actor)
    value = {"target_database": database, "source_database": state["active"], "revision": state["revision"],
             "already_active": False, "can_apply": True, "requires_credentials": access is None,
             "blockers": [], "warnings": target_files["warnings"], "files_count": target_files["files_count"],
             "target_kind": "managed" if operation else "configured", "previously_reviewed": True,
             "operation_id": operation["id"] if operation else None}
    value["review_hash"] = digest({"state": state, "identity": identity, "target_files": target_files,
                                  "target_native": target_native, "source_files": source_files,
                                  "source_native": source_native, "operation_id": value["operation_id"]})
    return value, {"identity": identity, "operation": operation, "source_files": source_files,
                   "source_native": source_native, "target_files": target_files, "target_native": target_native,
                   "access": access}


def review_selection(database, actor):
    service = _service()
    service._authorize(actor)
    with service._ready_guard():
        try:
            return_value = _preview_for_database(database, actor, selection.read_state())
            return return_value[0] if isinstance(return_value, tuple) else return_value
        except TransferError:
            raise
        except Exception as error:
            raise TransferError("The selected database could not be checked safely. Keep the current database and inspect the selected copy before retrying.") from error


def _preview_for_database(database, actor, state):
    if database not in {state["active"], state["configured"]["name"]}:
        operation = _find_operation(database)
        if operation:
            reviewed = _preview(operation["id"], actor)
            if isinstance(reviewed, tuple):
                reviewed[0].update(target_kind="managed", operation_id=operation["id"],
                                   previously_reviewed=bool(reviewed[1].get("identity")))
            return reviewed
    return _selection_preview(database, actor, state)


def _verify_first_restore(operation, database, verified):
    """Keep archive equality even when another copy has since been selected."""
    expected = operation["core_plan"]["target_fingerprint"]
    _close_target_read_alias(database)
    creation = store.operation_dir(operation["id"]) / "restore-target.json"
    if not creation.exists() and not creation.is_symlink():
        return postgres.verify_restore(verified, expected, destination=database)
    from .databases import _cluster, _ownership

    cluster = _cluster()
    identity = _ownership(operation, cluster)
    target = {"database": database, "oid": identity["oid"], "server_major": cluster["server_major"]}
    source = next((row["database"] for row in cluster["databases"]
                   if postgres._target_fingerprint(cluster["params"], row, target) == expected), None)
    if source is None:
        raise TransferError("The original restore source identity changed. Preserve this copy and review a new backup restore.")
    with selection.database_scope(source):
        return postgres.verify_restore(verified, expected, destination=database)


def _preview(operation_id, actor):
    service = _service()
    state = selection.read_state()
    operation, database = _completed(operation_id)
    value = {"target_database": database, "source_database": state["active"],
             "revision": state["revision"], "requires_credentials": False, "blockers": [],
             "can_apply": False, "already_active": database == state["active"]}
    if value["already_active"]:
        return value
    receipt_path = _receipt_path(operation)
    if receipt_path.exists() or receipt_path.is_symlink():
        return _selection_preview(database, actor, state, operation)
    verified = service._verified(operation)
    _verify_first_restore(operation, database, verified)
    target_files = _application_snapshot(database)
    target_native = _native_snapshot(database)
    source_files = _application_snapshot(state["active"])
    source_native = _native_snapshot(state["active"])
    access = _administrator(database, actor)
    value.update(can_apply=True, requires_credentials=access is None,
                 files_count=target_files["files_count"], warnings=target_files["warnings"])
    value["review_hash"] = digest({"operation": operation_id, "package": operation["package_sha256"],
                                  "state": state, "target_files": target_files,
                                  "target_native": target_native,
                                  "source_files": source_files, "source_native": source_native})
    return value, {"target_files": target_files, "source_files": source_files,
                   "target_native": target_native, "source_native": source_native,
                   "operation": operation, "access": access}


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
        _remember_source(state, evidence["source_native"])
        creation = store.operation_dir(operation_id) / "restore-target.json"
        if creation.exists() or creation.is_symlink():
            from .databases import managed_identity
            _remember(state, database, managed_identity(evidence["operation"]), evidence["operation"])
        value = {**state, "active": database, "previous": state["active"],
                 "revision": revision + 1, "operation_id": operation_id, "changed_at": store.now(),
                 "actor_name": actor.get_username(), "maintenance_generation": generation,
                 "activation": {"source_native": evidence["source_native"],
                                "source_files": evidence["source_files"], "access": access}}
        selection.write_state(value, expected_revision=revision)
        return value


def select(database, actor, review_hash, generation, revision, destination_confirmation,
           confirmed_storage=False, username="", password=""):
    """Explicitly review current contents; never reinterpret this as rollback."""
    service = _service()
    service._authorize(actor)
    with store.execution_lock(), service._ready_guard(generation):
        state = selection.read_state()
        _confirmation(state, generation, revision, database, destination_confirmation, confirmed_storage)
        reviewed = _preview_for_database(database, actor, state)
        if not isinstance(reviewed, tuple):
            raise TransferError("This database is already active.")
        current, evidence = reviewed
        if not current["can_apply"] or current["review_hash"] != review_hash:
            raise TransferError("The destination, database records or matching files changed. Review the selection again.")
        access = _administrator(database, actor, username, password, required=True)
        _remember_source(state, evidence["source_native"])
        if "identity" in evidence:
            _remember(state, database, evidence["identity"], evidence["operation"])
        elif evidence["operation"]:
            creation = store.operation_dir(evidence["operation"]["id"]) / "restore-target.json"
            if creation.exists() or creation.is_symlink():
                from .databases import managed_identity
                _remember(state, database, managed_identity(evidence["operation"]), evidence["operation"])
        value = {**state, "active": database, "previous": state["active"],
                 "revision": revision + 1, "operation_id": current["operation_id"], "changed_at": store.now(),
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
        return ["Quick recovery expired when maintenance was turned off. Both databases remain stored. Review a new switch in Manage databases to use a retained copy."]
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
            raise TransferError("Rollback is unavailable after maintenance ends. Both databases were retained; use Manage databases to review a new switch against their current contents.")
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
