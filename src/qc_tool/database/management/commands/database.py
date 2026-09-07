"""Django command discovery adapter for the application-wide database lifecycle."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import DatabaseError

from qc_tool.database.deployment import manage_database


class Command(BaseCommand):
    help = "Initialize draft models or plan/check/apply the released QC Tool migration graph."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("plan", "check", "apply"))
        parser.add_argument("--database", default="default")
        parser.add_argument("--lock-timeout-ms", type=int, default=5000)
        parser.add_argument("--statement-timeout-ms", type=int, default=300000)

    def handle(self, *args, **options):
        for name in ("lock_timeout_ms", "statement_timeout_ms"):
            if not 1 <= options[name] <= 2147483647:
                raise CommandError(f"{name} must be between 1 and 2147483647.")
        try:
            manage_database(
                options["action"], database=options["database"], stdout=self.stdout,
                lock_timeout_ms=options["lock_timeout_ms"],
                statement_timeout_ms=options["statement_timeout_ms"],
            )
        except DatabaseError as error:
            raise CommandError(
                "Database migration failed. Inspect the database and migration log "
                "before retrying; non-atomic migrations may need forward repair."
            ) from error
