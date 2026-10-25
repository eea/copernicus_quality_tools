"""Read-only cluster inventory and explicit removal of unused owned copies.

Only a generated restore destination with the original private ownership
journal, PostgreSQL OID, owner and unguessable database marker can be removed.
The configured database and the current/retained selections are always protected.
"""

from datetime import datetime
import re

from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections

from qc_tool.database import selection
from qc_tool.database.deployment import SchemaInitializer
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.services.maintenance.state import MaintenanceError, read_status

from . import postgres, store
from .errors import TransferError


def _service():
    from . import service
    return service


def _cluster():
    """Inspect catalog metadata without connecting to other databases."""
    params = postgres._params()
    with postgres._database(params) as (handle, info):
        with handle.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            owner, _can_create = postgres._creation_role(cursor)
            cursor.execute("""SELECT d.oid, d.datname, d.datdba, d.datallowconn,
                shobj_description(d.oid, 'pg_database'),
                CASE WHEN has_database_privilege(d.oid, 'CONNECT')
                    OR pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER')
                    THEN pg_database_size(d.oid) ELSE NULL END,
                (SELECT count(*) FROM pg_stat_activity a WHERE a.datid=d.oid
                    AND a.backend_type IN ('client backend', 'parallel worker')),
                EXISTS(SELECT 1 FROM pg_prepared_xacts p WHERE p.database=d.datname)
                FROM pg_database d WHERE NOT d.datistemplate ORDER BY d.datname""")
            rows = []
            while batch := cursor.fetchmany(256):
                rows.extend(dict(zip(("oid", "database", "owner_oid", "allow_connections",
                                      "marker", "bytes", "clients", "prepared_transactions"), row))
                            for row in batch)
    return {"params": params, "server_major": info["server_major"], "owner_oid": owner,
            "databases": rows}


def _operation_database(operation):
    destination = operation.get("destination") or {}
    if not isinstance(destination, dict):
        raise TransferError("The restore operation has an invalid destination journal.")
    name = destination.get("database") or operation.get("result", {}).get("target_database")
    if name is not None and not selection._valid_name(name):
        raise TransferError("The restore operation has an invalid database name.")
    return name


def _creation_journal(operation, cluster):
    """Bind a restore journal to this cluster even after another DB is selected.

    Version-one creation evidence hashes the original source database identity.
    Match that hash against the current catalog rather than the selected DB; a
    missing/recreated source fails closed. Never adopt a database by name alone.
    """
    operation_id = operation["id"]
    name = postgres.restore_database_name(operation_id)
    if (operation.get("kind") != "import" or operation.get("profile") != "database"
            or _operation_database(operation) not in {None, name}):
        raise TransferError("This database was not created as this operation's managed restore copy.")
    journal = store.read_json(store.operation_dir(operation_id) / "restore-target.json")
    possible = {
        postgres._target_fingerprint(cluster["params"],
            {"oid": row["oid"], "database": row["database"]},
            {"database": name, "oid": 0, "server_major": cluster["server_major"]})
        for row in cluster["databases"]
    }
    fingerprint = journal.get("source_fingerprint") if isinstance(journal, dict) else None
    if not isinstance(fingerprint, str) or fingerprint not in possible:
        raise TransferError("The restore copy's original cluster and source identity cannot be verified. Ask the database administrator to inspect it.")
    postgres._validate_creation_journal(journal, operation_id=operation_id, name=name,
        package_sha256=operation.get("package_sha256"), source_fingerprint=fingerprint,
        owner=cluster["owner_oid"])
    return journal


def _ownership(operation, cluster):
    journal = _creation_journal(operation, cluster)
    name = journal["database"]
    row = next((row for row in cluster["databases"] if row["database"] == name), None)
    if (row is None or journal["status"] not in {"owned", "ready"}
            or type(journal["target_oid"]) is not int or row["oid"] != journal["target_oid"]
            or row["owner_oid"] != journal["owner_oid"] or row["marker"] != journal["marker"]):
        raise TransferError("The restore database identity or ownership changed. It was preserved; ask the database administrator to inspect it.")
    return {"database": name, "oid": row["oid"], "owner_oid": row["owner_oid"],
            "marker": journal["marker"], "source_fingerprint": journal["source_fingerprint"]}


def managed_identity(operation):
    """Small deterministic ownership proof for an already reviewed restore copy."""
    return _ownership(operation, _cluster())


def _deletion(operation):
    path = store.operation_dir(operation["id"]) / "database-deletion.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = store.read_json(path)
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1
            or value.get("operation_id") != operation["id"]
            or value.get("database") != postgres.restore_database_name(operation["id"])
            or type(value.get("target_oid")) is not int or value["target_oid"] <= 0
            or not isinstance(value.get("marker"), str) or not re.fullmatch(
                "qc-tool-restore:" + re.escape(operation["id"]) + ":[0-9a-f]{64}", value["marker"])
            or type(value.get("revision")) is not int or value["revision"] < 0
            or type(value.get("generation")) is not int or value["generation"] < 0
            or not isinstance(value.get("requested_by"), str)
            or value.get("status") not in {"requested", "completed"}):
        raise TransferError("The database deletion journal is invalid. Operator recovery is required.")
    try:
        for key in (("requested_at", "completed_at") if value["status"] == "completed" else ("requested_at",)):
            if datetime.fromisoformat(value[key]).utcoffset() is None:
                raise ValueError
    except (KeyError, ValueError, TypeError):
        raise TransferError("The database deletion journal has invalid timestamps. Operator recovery is required.") from None
    return value


def _operations():
    path = store._directory_path()
    if not path.exists() and not path.is_symlink():
        return [], []
    operations, warnings = [], []
    for child in store.directory().iterdir():
        if child.is_dir() and not child.is_symlink():
            try:
                operation = store.read_operation(child.name)
                if operation.get("kind") == "import" and operation.get("profile") == "database":
                    journal = child / "restore-target.json"
                    if _operation_database(operation) or journal.exists() or journal.is_symlink():
                        operations.append(operation)
            except TransferError:
                warnings.append("An unreadable restore journal was excluded. Its database remains protected from removal.")
    return sorted(operations, key=lambda operation: operation["created_at"], reverse=True), warnings


def _protection(name, state):
    blockers = []
    if name == state["active"]:
        blockers.append("This is the database QC Tool is using now.")
    if name == state["configured"]["name"]:
        blockers.append("This is the deployment's configured database and is kept for recovery.")
    if name == state.get("previous"):
        blockers.append("This is the previous database retained for recovery after the last switch.")
    return blockers


def _dependent_copies(identity, cluster, operations=None):
    """Retain a source while another present copy needs its ownership proof."""
    if operations is None:
        operations, _warnings = _operations()
    dependent = []
    for operation in operations:
        child_name = postgres.restore_database_name(operation["id"])
        if child_name == identity["database"]:
            continue
        expected = postgres._target_fingerprint(cluster["params"], identity,
            {"database": child_name, "oid": 0, "server_major": cluster["server_major"]})
        try:
            child = _ownership(operation, cluster)
            if child["source_fingerprint"] == expected:
                dependent.append(child_name)
        except TransferError:
            # An absent or unproven child has no supported management authority
            # that removing this source could invalidate.
            continue
    return sorted(dependent)


def _dependency_message(names):
    return ("Keep this database while these restore copies depend on its original identity: "
            + ", ".join(names) + ". Remove unused dependent copies first.")


def inventory(actor):
    _service()._authorize(actor)
    state = selection.read_state()
    result = {"supported": connection.vendor == "postgresql", "available": False,
              "active_database": state["active"], "configured_database": state["configured"]["name"],
              "previous_database": state.get("previous"), "revision": state["revision"],
              "databases": [], "warnings": [], "message": ""}
    if not result["supported"]:
        result["message"] = "Multiple database copies are available with PostgreSQL. This installation uses one SQLite database."
        return result
    cluster = _cluster()
    operations, warnings = _operations()
    try:
        maintenance = read_status()
        pin = active_operation()
    except MaintenanceError as error:
        raise TransferError(str(error)) from error
    busy = bool(pin) or store.execution_active()
    readiness = []
    if not maintenance["enabled"] or maintenance["phase"] != "ready":
        readiness.append("Turn on maintenance and wait for it to be ready before deleting a database copy.")
    if busy:
        readiness.append("Finish or recover the current transfer before deleting a database copy.")
    catalog = {row["database"]: row for row in cluster["databases"]}
    entries, represented = [], set()
    for operation in operations:
        name = _operation_database(operation) or postgres.restore_database_name(operation["id"])
        row = catalog.get(name)
        source = ((operation.get("result") or {}).get("source_details")
                  or (operation.get("plan") or {}).get("source_details") or {})
        source = source if isinstance(source, dict) else {}
        entry = {"database": name, "name": name, "operation_id": operation["id"],
                 "created_at": operation["created_at"], "present": row is not None,
                 "bytes": row["bytes"] if row else None, "managed": False,
                 "active": name == state["active"], "configured": name == state["configured"]["name"],
                 "retained": name == state.get("previous"), "status": "restore",
                 "label": "Restored copy" if operation["status"] == "completed" else "Restore destination",
                 "completed_restore": operation["status"] == "completed" and bool(operation.get("result", {}).get("verified")),
                 "can_review_switch": False, "can_delete": False, "delete_blockers": [],
                 "operation_status": operation["status"]}
        entry["source_details"] = {key: value for key, value in source.items()
            if key in {"source_database", "exported_at", "app_version"}
            and isinstance(value, str) and len(value) <= 512}
        blockers = _protection(name, state)
        try:
            deletion = _deletion(operation)
            if deletion:
                entry.update(deletion_pending=deletion["status"] == "requested",
                             deleted=deletion["status"] == "completed",
                             status="deleted" if deletion["status"] == "completed" else "deleting",
                             label="Deleted copy" if deletion["status"] == "completed" else "Deletion needs completion")
            if row is not None:
                identity = _ownership(operation, cluster)
                entry["managed"] = True
                dependent = _dependent_copies(identity, cluster, operations)
                if dependent:
                    entry["dependent_databases"] = dependent
                    blockers.append(_dependency_message(dependent))
                if row["clients"] or row["prepared_transactions"]:
                    blockers.append("Another client or prepared transaction is using this copy. Disconnect it before deletion.")
            elif deletion and deletion["status"] == "requested":
                entry.update(managed=True, can_complete_deletion=True)
            else:
                blockers.append("The database is no longer present on this PostgreSQL server.")
            if deletion and row and deletion["status"] == "completed":
                blockers.append("A database with this name exists after a recorded deletion. It cannot be removed through this operation.")
            entry["can_review_switch"] = bool(entry["completed_restore"] and row and not entry["active"] and not deletion)
        except TransferError as error:
            blockers.append(str(error))
        if entry["active"]:
            entry.update(status="active", label="In use now")
        elif entry["retained"]:
            entry.update(status="retained", label="Previous database")
        blockers.extend(readiness)
        entry.update(delete_blockers=blockers,
                     can_delete=bool(entry["managed"] and (row or entry.get("can_complete_deletion")) and not blockers))
        entry["can_inspect"] = bool(row and (entry["managed"] or entry["active"] or entry["configured"] or entry["retained"]))
        entries.append(entry)
        represented.add(name)
    for name, row in catalog.items():
        if name in represented or (name == "postgres" and not _protection(name, state)):
            continue
        blockers = _protection(name, state)
        active, configured, retained = name == state["active"], name == state["configured"]["name"], name == state.get("previous")
        entries.append({"database": name, "name": name, "operation_id": None, "present": True,
                        "bytes": row["bytes"], "active": active, "configured": configured,
                        "retained": retained, "managed": False, "completed_restore": False,
                        "status": "active" if active else "retained" if retained else "configured" if configured else "external",
                        "label": "In use now" if active else "Previous database" if retained else "Configured database" if configured else "Other database",
                        "can_delete": False, "can_review_switch": False,
                        "delete_blockers": blockers + ["This database has no matching QC Tool restore ownership journal. Manage it with your database administrator."]})
    # A selected database can be unavailable; retain its identity in the UI.
    names = {entry["database"] for entry in entries}
    for name in {state["active"], state["configured"]["name"], state.get("previous")} - names - {None}:
        entries.append({"database": name, "name": name, "operation_id": None, "present": False,
                        "bytes": None, "active": name == state["active"], "configured": name == state["configured"]["name"],
                        "retained": name == state.get("previous"), "managed": False, "completed_restore": False,
                        "status": "missing", "label": "Database unavailable", "can_delete": False,
                        "can_review_switch": False, "delete_blockers": ["This database is not present in the server catalog."]})
    from .control import can_review_selection
    by_id = {operation["id"]: operation for operation in operations}
    for entry in entries:
        entry.setdefault("can_inspect", bool(entry["present"] and (entry["active"] or entry["configured"] or entry["retained"])))
        entry["can_review_selection"] = bool(entry["present"] and not entry["active"]
            and not entry.get("deletion_pending") and not entry.get("deleted")
            and can_review_selection(entry["database"], state=state,
                                     operation=by_id.get(entry.get("operation_id"))))
    entries.sort(key=lambda entry: (not entry["active"], not entry["retained"], not entry["configured"], entry["database"]))
    result.update(available=True, databases=entries, warnings=warnings,
                  total_bytes=sum(row["bytes"] or 0 for row in catalog.values()),
                  maintenance_ready=not readiness, generation=maintenance["generation"])
    return result


def details(database, actor):
    """Fast current statistics for a known QC Tool database, never record values.

    PostgreSQL's catalog row estimates avoid scanning every record on a browse
    request. They can be stale after a restore; exact archive verification is
    deliberately reserved for the explicit switch review.
    """
    service = _service()
    service._authorize(actor)
    if connection.vendor != "postgresql":
        raise TransferError("Database copy inspection requires PostgreSQL.")
    state, cluster = selection.read_state(), _cluster()
    protected = database in {state["active"], state["configured"]["name"], state.get("previous")}
    operation = None
    if not protected:
        operations, _warnings = _operations()
        operation = next((value for value in operations if _operation_database(value) == database), None)
        if operation is None or _deletion(operation):
            raise TransferError("Choose a current or managed QC Tool database copy from the database list.")
        _ownership(operation, cluster)
    row = next((value for value in cluster["databases"] if value["database"] == database), None)
    if row is None:
        raise TransferError("This database is not available on the configured PostgreSQL server.")
    if database == state.get("previous"):
        recorded = ((state.get("activation") or {}).get("source_native") or {}).get("oid")
        if type(recorded) is not int or recorded != row["oid"]:
            raise TransferError("The retained database's recorded identity is unavailable or changed. Keep it protected and ask the database administrator to inspect it.")
    alias = selection.alias_for_database(database)
    inspected = connections[alias]
    previous_timeout = None
    try:
        with inspected.cursor() as cursor:
            if alias == "default":
                cursor.execute("SHOW statement_timeout")
                previous_timeout = cursor.fetchone()[0]
            cursor.execute("SET statement_timeout = '10s'")
            cursor.execute("SELECT oid FROM pg_database WHERE datname=current_database()")
            if cursor.fetchone() != (row["oid"],):
                raise TransferError("The database identity changed. Reload the database list.")
            cursor.execute(f"""SELECT n.nspname, c.relname,
                CASE WHEN c.reltuples >= 0 AND c.relkind <> 'p' THEN c.reltuples::bigint ELSE NULL END,
                pg_total_relation_size(c.oid)
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE c.relkind IN ('r','p','m') AND {postgres._SYSTEM_NAMESPACE}
                ORDER BY n.nspname,c.relname""")
            tables = []
            while batch := cursor.fetchmany(256):
                tables.extend({"schema": schema, "name": name, "estimated_rows": rows, "bytes": size}
                              for schema, name, rows, size in batch)
        try:
            SchemaInitializer(inspected).check()
            schema = {"ready": True, "message": "The database matches current models."}
        except CommandError as error:
            schema = {"ready": False, "message": str(error)}
        estimates = [table["estimated_rows"] for table in tables if table["estimated_rows"] is not None]
        return {"database": database, "bytes": row["bytes"], "table_count": len(tables),
                "tables": tables, "schema": schema, "operation_id": operation["id"] if operation else None,
                "estimated_rows": sum(estimates) if len(estimates) == len(tables) else None,
                "counts_are_estimates": True,
                "counts_note": "Row counts are PostgreSQL estimates and may be unavailable or stale after a restore. Switch review verifies the full database separately."}
    except DatabaseError:
        raise TransferError("This database copy could not be inspected. Its data was not changed.") from None
    finally:
        if alias != "default":
            inspected.close()
        elif previous_timeout is not None:
            try:
                with inspected.cursor() as cursor:
                    cursor.execute("SELECT set_config('statement_timeout', %s, false)", [previous_timeout])
            except DatabaseError:
                # Discard a broken session rather than leak a changed timeout
                # into the next request using the default connection.
                inspected.close()


def _drop(identity, params):
    """No FORCE, no session termination, no replacement of existing content."""
    import psycopg2
    from psycopg2 import sql

    handle = None
    try:
        handle = psycopg2.connect(**params)
        handle.autocommit = True
        with handle.cursor() as cursor:
            cursor.execute("SET statement_timeout = '15s'")
            cursor.execute("SET lock_timeout = '3s'")
            actual = postgres._created_database(cursor, identity["database"])
            if (actual is None or actual[0] != identity["oid"]
                    or actual[1] != identity["owner_oid"] or actual[3] != identity["marker"]):
                raise TransferError("The database identity changed before deletion. It was preserved.")
            cursor.execute("""SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datid=%s
                AND backend_type IN ('client backend','parallel worker'))
                OR EXISTS(SELECT 1 FROM pg_prepared_xacts WHERE database=%s)""",
                [identity["oid"], identity["database"]])
            if cursor.fetchone()[0]:
                raise TransferError("The database has connected clients or prepared transactions. Disconnect them before retrying deletion.")
            cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(identity["database"])))
    except TransferError:
        raise
    except Exception:
        raise TransferError("The database deletion could not be confirmed. It was never forced; reload the database list and retry completion if needed.") from None
    finally:
        if handle is not None:
            handle.close()


def delete(operation_id, actor, *, generation, revision, destination_confirmation):
    service = _service()
    service._authorize(actor)
    if type(generation) is not int or generation < 0:
        raise TransferError("Reload the database list to confirm the current maintenance generation.")
    with store.execution_lock(), service._ready_guard(generation):
        state = selection.read_state()
        if type(revision) is not int or state["revision"] != revision:
            raise TransferError("The active database changed. Reload the database list before deleting a copy.")
        operation = store.read_operation(operation_id)
        name = postgres.restore_database_name(operation_id)
        if destination_confirmation != name:
            raise TransferError("Enter the exact database name to confirm permanent deletion of this copy.")
        blockers = _protection(name, state)
        if blockers:
            raise TransferError(" ".join(blockers))
        cluster = _cluster()
        deletion = _deletion(operation)
        row = next((row for row in cluster["databases"] if row["database"] == name), None)
        if deletion and row is None:
            # A lost DROP acknowledgement is resolved from durable prior intent;
            # absence alone never authorizes removing a replacement database.
            ownership = _creation_journal(operation, cluster)
            if (ownership["target_oid"] != deletion["target_oid"]
                    or ownership["marker"] != deletion["marker"]):
                raise TransferError("The original database deletion identity changed. Operator inspection is required.")
            if deletion["status"] != "completed":
                deletion.update(status="completed", completed_at=store.now())
                store.write_json(store.operation_dir(operation_id) / "database-deletion.json", deletion)
            operation.update(database_deleted_at=deletion["completed_at"],
                             database_deletion_requested_at=deletion["requested_at"])
            store.save_operation(operation)
            return {"database": name, "deleted": True, "operation_id": operation_id}
        if deletion and deletion["status"] == "completed":
            raise TransferError("This copy was already deleted. A replacement database with the same name is protected.")
        identity = _ownership(operation, cluster)
        dependent = _dependent_copies(identity, cluster)
        if dependent:
            raise TransferError(_dependency_message(dependent))
        if row["clients"] or row["prepared_transactions"]:
            raise TransferError("Another client or prepared transaction is using this copy. Disconnect it before deletion.")
        if deletion and any(deletion[key] != identity[source] for key, source in (
                ("database", "database"), ("target_oid", "oid"), ("marker", "marker"))):
            raise TransferError("The database identity changed after deletion was requested. It was preserved.")
        if not deletion:
            deletion = {"version": 1, "operation_id": operation_id, "database": name,
                        "target_oid": identity["oid"], "marker": identity["marker"],
                        "revision": revision, "generation": generation, "status": "requested",
                        "requested_at": store.now(), "requested_by": actor.get_username()}
            store.write_json(store.operation_dir(operation_id) / "database-deletion.json", deletion)
        operation["database_deletion_requested_at"] = deletion["requested_at"]
        store.save_operation(operation)
        _drop(identity, cluster["params"])
        deletion.update(status="completed", completed_at=store.now())
        store.write_json(store.operation_dir(operation_id) / "database-deletion.json", deletion)
        operation["database_deleted_at"] = deletion["completed_at"]
        store.save_operation(operation)
        return {"database": name, "deleted": True, "operation_id": operation_id}
