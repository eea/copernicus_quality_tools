"""Pin read-only source inspection and separately owned writable candidates."""

from contextlib import contextmanager

from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections
from django.db.migrations.recorder import MigrationRecorder

from qc_tool.database import migration_engine, selection
from qc_tool.database.transfers import postgres
from qc_tool.database.transfers.databases import managed_identity
from qc_tool.database.transfers.errors import TransferError


def inspect_migrations(database, *, include_applied_history=False):
    alias = selection.alias_for_database(database) if connection.vendor == "postgresql" else "default"
    try:
        handle = connections[alias]
        report = migration_engine.migration_status(handle)
        if include_applied_history:
            # Presentation only: recorder dates must never affect migration-plan
            # hashes, supported-source recognition or candidate adoption reviews.
            # applied_migrations() reads this same pinned connection and does not
            # create an absent recorder on history-free installations.
            applied = MigrationRecorder(handle).applied_migrations()
            report = {**report, "applied_history": [
                {"app": app, "name": name,
                 "applied_at": migration.applied.isoformat() if migration.applied else None}
                for (app, name), migration in sorted(applied.items())
            ]}
        return report
    except (CommandError, DatabaseError) as error:
        raise TransferError("The database migration history or schema cannot be verified. Inspect it before upgrading.") from error
    finally:
        if alias != "default":
            connections[alias].close()


@contextmanager
def candidate_connection(operation):
    """Pin one writable alias after checking physical ownership and isolation."""
    name = operation["destination"]["database"]
    state = selection.read_state()
    if name in {state["active"], state.get("previous"), selection.configured_connection()["NAME"]}:
        raise TransferError("An active, previous or configured database can never be a migration target.")
    if name != postgres.restore_database_name(operation["id"]):
        raise TransferError("The migration candidate is not owned by this operation.")
    identity = managed_identity(operation)
    params = {**postgres._params(), "dbname": name}
    with postgres._database(params) as (handle, info):
        if info["oid"] != identity["oid"]:
            raise TransferError("Candidate database ownership or physical identity changed. It was preserved.")
        postgres._require_isolated_target(handle, info)
    alias = "qc_upgrade_" + operation["id"].replace("-", "")
    config = selection.pinned_connection_settings(name)
    config.update(NAME=name, ENGINE="django.db.backends.postgresql", CONN_MAX_AGE=0)
    config.setdefault("OPTIONS", {})
    connections.databases[alias] = config
    candidate = connections[alias]
    try:
        candidate.ensure_connection()
        with candidate.cursor() as cursor:
            cursor.execute("SELECT current_database(), oid FROM pg_database WHERE datname=current_database()")
            if cursor.fetchone() != (name, identity["oid"]):
                raise TransferError("The candidate physical database changed before migration.")
        # The check runs on this connection, so it excludes only this backend.
        postgres._require_isolated_target(candidate.connection, {"oid": identity["oid"], "database": name})
        yield candidate
    finally:
        candidate.close()
