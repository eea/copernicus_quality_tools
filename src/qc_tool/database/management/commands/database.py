"""Django command discovery adapter for the application-wide database lifecycle."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import DatabaseError

from qc_tool.database.deployment import manage_database
from qc_tool.database import selection
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.services.maintenance.state import MaintenanceError


class Command(BaseCommand):
    help = "Inspect current-model readiness or explicitly initialize an empty database."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("plan", "check", "apply"))
        parser.add_argument("--database", default="default")
        parser.add_argument("--lock-timeout-ms", type=int, default=5000)
        parser.add_argument("--statement-timeout-ms", type=int, default=300000)
        parser.add_argument("--allow-maintenance-recovery", action="store_true",
                            help="Default/check only: admit a verified read-only recovery UI while maintenance remains ready.")

    def handle(self, *args, **options):
        recovery = options["allow_maintenance_recovery"]
        if recovery and (options["action"] != "check" or options["database"] != "default"):
            raise CommandError("--allow-maintenance-recovery is supported only for database check --database default.")
        for name in ("lock_timeout_ms", "statement_timeout_ms"):
            if not 1 <= options[name] <= 2147483647:
                raise CommandError(f"{name} must be between 1 and 2147483647.")
        try:
            manage_database(
                options["action"], database=options["database"], stdout=self.stdout,
                lock_timeout_ms=options["lock_timeout_ms"],
                statement_timeout_ms=options["statement_timeout_ms"],
            )
        except (DatabaseError, CommandError, TransferError) as error:
            if recovery:
                from qc_tool.database.recovery import maintenance_recovery_database
                try:
                    maintenance_recovery_database()
                except (TransferError, MaintenanceError) as recovery_error:
                    # The shell must not initialize an empty/recreated selected
                    # restore database after a failed recovery check.
                    try:
                        can_initialize = not isinstance(recovery_error, MaintenanceError) and selection.read_state()["revision"] == 0
                    except TransferError:
                        can_initialize = False
                    raise CommandError(
                        "Active database is not ready. " + str(recovery_error),
                        returncode=1 if can_initialize else 2,
                    ) from error
                self.stdout.write("maintenance-recovery")
                self.stderr.write("Maintenance recovery startup admitted. The active database is unchanged; ordinary writes remain blocked.")
                return
            if isinstance(error, CommandError):
                raise
            if isinstance(error, TransferError):
                raise CommandError(str(error)) from error
            raise CommandError(
                "Database initialization or inspection failed. No existing schema "
                "is upgraded or reset; inspect the target before retrying."
            ) from error
        if recovery:
            self.stdout.write("ready")
