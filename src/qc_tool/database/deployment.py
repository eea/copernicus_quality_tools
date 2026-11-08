"""Explicit fresh initialization composed with read-only schema inspection."""

from contextlib import contextmanager
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from qc_tool.database.policy import DatabasePolicyError, load_policy
from qc_tool.database.schema import SchemaInspector

# Keep the application-wide advisory lock identity stable across refactors.
SCHEMA_LOCK = (1363366991, 1)


@contextmanager
def schema_lock(connection, *, lock_timeout_ms, statement_timeout_ms):
    """Serialize explicit initialization and restore session timeout settings."""
    if connection.vendor != "postgresql":
        yield
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", SCHEMA_LOCK)
        if not cursor.fetchone()[0]:
            raise CommandError("Another QC Tool database initialization job is running.")
        previous = {}
        try:
            for setting, value in (("lock_timeout", lock_timeout_ms),
                                   ("statement_timeout", statement_timeout_ms)):
                cursor.execute("SELECT current_setting(%s)", [setting])
                previous[setting] = cursor.fetchone()[0]
                cursor.execute("SELECT set_config(%s, %s, false)", [setting, f"{value}ms"])
            yield
        finally:
            if connection.connection is not None and connection.is_usable():
                try:
                    for setting, value in previous.items():
                        cursor.execute("SELECT set_config(%s, %s, false)", [setting, value])
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s, %s)", SCHEMA_LOCK)


class SchemaInitializer(SchemaInspector):
    """Only an entirely empty target may run committed native migrations here."""

    def apply(self, *, stdout, lock_timeout_ms, statement_timeout_ms):
        with schema_lock(self.connection, lock_timeout_ms=lock_timeout_ms,
                         statement_timeout_ms=statement_timeout_ms):
            report = self.inspect()
            if report["state"] != "empty":
                self.check()
                stdout.write("Current model schema already exists; schema and data unchanged.")
                return
            # Only an entirely empty target can run native migrations here.
            # Existing databases use the separate operation-owned candidate path.
            call_command("migrate", database=self.connection.alias,
                         interactive=False, stdout=stdout)
            self.check()
            stdout.write("Initialized the empty database from committed Django migrations.")


def manage_database(action, *, database, stdout, lock_timeout_ms, statement_timeout_ms):
    try:
        load_policy()
    except DatabasePolicyError as error:
        raise CommandError(str(error)) from error
    initializer = SchemaInitializer(connections[database])
    if action == "apply":
        initializer.apply(stdout=stdout, lock_timeout_ms=lock_timeout_ms,
                          statement_timeout_ms=statement_timeout_ms)
    elif action == "check":
        initializer.check()
    else:
        report = initializer.inspect()
        if report["state"] == "incompatible":
            initializer.check()
        stdout.write("Empty database: explicit apply will initialize current models." if report["state"] == "empty"
                     else "Current model schema is ready; apply would leave schema and data unchanged.")
