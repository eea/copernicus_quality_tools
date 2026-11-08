"""Execute native migrations only after explicit candidate admission."""

from io import StringIO
from pathlib import Path
from uuid import UUID

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor

from qc_tool.database.policy import BASELINE_TARGETS
from .inspection import inspect_source, migration_status


def require_candidate(connection, operation_id):
    """A second guard behind the service's stronger OID/ownership verification."""
    try:
        identifier = UUID(str(operation_id))
        if str(identifier) != str(operation_id):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise CommandError("A canonical restore-operation UUID is required.") from error
    expected = "qc_restore_" + identifier.hex
    name = str(connection.settings_dict["NAME"])
    if connection.alias == "default" or connections[connection.alias] is not connection:
        raise CommandError("Migration adoption and upgrades require a separately registered, pinned candidate connection.")
    if connection.vendor == "postgresql":
        if name != expected:
            raise CommandError("Migrations may only change the operation-owned restore database.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_setting('transaction_read_only')")
            actual, readonly = cursor.fetchone()
        if actual != expected or readonly != "off":
            raise CommandError("The candidate connection must be pinned to the writable operation-owned restore database.")
    elif connection.vendor == "sqlite":
        if Path(name).name != expected + ".sqlite3":
            raise CommandError("SQLite migration tests require an operation-owned disposable candidate file.")
    else:
        raise CommandError("Managed migration candidates support PostgreSQL and disposable SQLite tests only.")


def review_candidate(connection, expected_plan_hash, expected_source_fingerprint):
    report = migration_status(connection)
    if (not expected_plan_hash or report["plan_hash"] != expected_plan_hash
            or not expected_source_fingerprint or report["source_fingerprint"] != expected_source_fingerprint):
        raise CommandError("The candidate schema, migration history or installed migration files changed. Review the migration again.")
    if report["state"] not in {"legacy", "pending", "ready"}:
        raise CommandError("The candidate does not match a supported source schema/history. No adoption or repair was performed.")
    return report


def _adopt_baseline(connection):
    """Use Django's recorder through its executor after strict source inspection."""
    report = inspect_source(connection)
    if report["state"] != "ready":
        raise CommandError("The candidate is not the supported v3.0.0 schema: " + "; ".join(report["problems"]))
    # The transaction makes graph adoption indivisible. No source business table
    # is changed; this records framework history as well as first-party history.
    # SQLite must disable FK enforcement before opening its schema transaction;
    # PostgreSQL keeps its normal native transactional DDL behavior.
    with connection.constraint_checks_disabled():
        with transaction.atomic(using=connection.alias):
            MigrationExecutor(connection).migrate(list(BASELINE_TARGETS.items()), fake=True)


def adopt_candidate_baseline(connection, *, operation_id, expected_plan_hash, expected_source_fingerprint,
                             lock_timeout_ms=5000, statement_timeout_ms=300000, stdout=None):
    from qc_tool.database.deployment import schema_lock

    require_candidate(connection, operation_id)
    with schema_lock(connection, lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms):
        report = review_candidate(connection, expected_plan_hash, expected_source_fingerprint)
        if report["state"] != "legacy":
            raise CommandError("Only a verified history-free v3.0.0 candidate can adopt the baseline.")
        _adopt_baseline(connection)
        return migration_status(connection)


def apply_candidate(connection, *, operation_id, expected_plan_hash, expected_source_fingerprint,
                    lock_timeout_ms=5000, statement_timeout_ms=300000, stdout=None):
    """Adopt the reviewed predecessor if needed, then run native forward migrate."""
    from qc_tool.database.deployment import SchemaInitializer, schema_lock

    require_candidate(connection, operation_id)
    with schema_lock(connection, lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms):
        report = review_candidate(connection, expected_plan_hash, expected_source_fingerprint)
        if report["state"] == "legacy":
            _adopt_baseline(connection)
            report = migration_status(connection)
        if report["pending"]:
            call_command("migrate", database=connection.alias, interactive=False, stdout=stdout or StringIO())
        SchemaInitializer(connection).check()
        return migration_status(connection)
