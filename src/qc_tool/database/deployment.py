"""Serialized, bounded schema application for the entire QC Tool database."""

from contextlib import contextmanager

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.migrations.loader import MigrationLoader

from qc_tool.database.policy import DatabasePolicyError
from qc_tool.database.policy import load_policy

# Stable two-integer PostgreSQL advisory-lock identity for all QC Tool releases.
MIGRATION_LOCK = (1363366991, 1)


def release_policy():
    try:
        return load_policy()
    except DatabasePolicyError as error:
        raise CommandError(str(error)) from error


@contextmanager
def migration_lock(connection, *, lock_timeout_ms, statement_timeout_ms):
    """Keep one migrator; fail quickly on busy DDL, including non-atomic work."""
    if connection.vendor != "postgresql":
        # SQLite deployment requires one external job and quiesced writers.
        yield
        return

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", MIGRATION_LOCK)
        if not cursor.fetchone()[0]:
            raise CommandError("Another QC Tool database migration job is running.")
        previous = {}
        try:
            for setting, value in (
                ("lock_timeout", lock_timeout_ms),
                ("statement_timeout", statement_timeout_ms),
            ):
                cursor.execute("SELECT current_setting(%s)", [setting])
                previous[setting] = cursor.fetchone()[0]
                cursor.execute("SELECT set_config(%s, %s, false)", [setting, f"{value}ms"])
            yield
        finally:
            # Closing a lost connection also releases its advisory lock. Do not
            # obscure the database error by attempting cleanup on a broken one.
            if connection.connection is not None and connection.is_usable():
                try:
                    for setting, value in previous.items():
                        cursor.execute("SELECT set_config(%s, %s, false)", [setting, value])
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s, %s)", MIGRATION_LOCK)


def manage_database(action, *, database, stdout, lock_timeout_ms, statement_timeout_ms):
    policy = release_policy()
    if policy["phase"] == "draft" and settings.IS_SECURE_ENVIRONMENT:
        raise CommandError(
            "This branch has a draft schema without migration history. Freeze the release policy "
            "before production deployment; do not apply it to a legacy database."
        )
    connection = connections[database]
    if policy["phase"] == "draft":
        if action == "plan":
            stdout.write(
                "Draft schema: database apply creates missing tables from current models. "
                "It does not upgrade existing tables; use a fresh development database "
                "after schema changes."
            )
        elif action == "apply":
            with migration_lock(
                connection,
                lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
            ):
                # Native syncdb creates all current models without writing history
                # files or transforming existing tables. No catalog data is seeded.
                call_command(
                    "migrate", database=database, run_syncdb=True,
                    interactive=False, stdout=stdout,
                )
                check_draft_tables(connection)
        else:
            check_draft_tables(connection)
        return
    loader = MigrationLoader(connection)
    missing = set(policy["baselines"].items()).difference(loader.disk_migrations)
    if missing:
        raise CommandError(f"Missing committed QC Tool baselines: {sorted(missing)}")
    loader.check_consistent_history(connection)
    if loader.detect_conflicts():
        raise CommandError("Conflicting database migrations; resolve dependencies before deployment.")

    if action == "plan":
        call_command("migrate", database=database, plan=True, stdout=stdout)
    elif action == "check":
        call_command("migrate", database=database, check_unapplied=True, stdout=stdout)
    else:
        with migration_lock(
            connection,
            lock_timeout_ms=lock_timeout_ms,
            statement_timeout_ms=statement_timeout_ms,
        ):
            call_command("migrate", database=database, interactive=False, stdout=stdout)
            call_command("migrate", database=database, check_unapplied=True, stdout=stdout)


def check_draft_tables(connection):
    """Check table/column presence only, never pretend to certify schema upgrades."""
    tables = set(connection.introspection.table_names())
    problems = []
    with connection.cursor() as cursor:
        for model in apps.get_models(include_auto_created=True):
            if not model._meta.can_migrate(connection):
                continue
            table = model._meta.db_table
            if table not in tables:
                problems.append(f"missing table {table}")
                continue
            actual = {
                column.name
                for column in connection.introspection.get_table_description(cursor, table)
            }
            expected = {field.column for field in model._meta.local_fields}
            if actual != expected:
                problems.append(f"columns differ in {table}")
    if problems:
        raise CommandError(
            "Draft schema is not ready: " + "; ".join(problems) +
            ". Create a fresh development database from the current models; "
            "no existing tables or data have been reset."
        )
