"""Operator recovery/control for the same maintenance service as the UI."""

import json

from django.core.management.base import BaseCommand, CommandError

from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


class Command(BaseCommand):
    help = "Control application maintenance without resetting or upgrading its database."
    # Recovery/status must also work while the application schema is offline.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("status", "on", "check", "off", "retire-worker"))
        parser.add_argument("--generation", type=int)
        parser.add_argument("--worker-url")
        parser.add_argument("--verified-stopped", action="store_true", help="Operator attests the retired worker and all its processes are stopped.")

    def handle(self, *args, **options):
        try:
            generation = options["generation"]
            action = options["action"]
            if generation is not None and generation < 0:
                raise CommandError("The maintenance generation must be nonnegative.")
            if action == "retire-worker":
                if not options["worker_url"] or not options["verified_stopped"] or generation is None:
                    raise CommandError("Retiring a worker requires --worker-url, --generation and --verified-stopped after verifying its processes are stopped.")
                state = maintenance.retire_worker(
                    options["worker_url"], "operator command", generation,
                    verified_stopped=True,
                )
            else:
                state = maintenance.read_status()
                if generation is None:
                    generation = state["generation"]
                if action == "on":
                    state = maintenance.enable("operator command", generation)
                    state = maintenance.advance(state["generation"])
                elif action == "check":
                    state = maintenance.advance(generation)
                elif action == "off":
                    state = maintenance.disable("operator command", generation)
            self.stdout.write(json.dumps({**state, "transfer_operation": active_operation()}, indent=2))
            if action in {"on", "check"} and state["phase"] != "ready":
                raise CommandError("Maintenance remains enabled, but work has not stopped. Resolve the reported blockers and check again.")
        except maintenance.MaintenanceError as exc:
            raise CommandError(str(exc)) from exc
