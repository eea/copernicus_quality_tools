"""Dedicated transfer runner and recovery, independent of QC workers."""

import json

from django.core.management.base import BaseCommand, CommandError

from qc_tool.database.transfers import service, store


class Command(BaseCommand):
    help = "Run, inspect, retry or cancel a durable administrator data transfer."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("run", "status", "retry", "cancel"))
        parser.add_argument("operation_id")

    def handle(self, *args, **options):
        try:
            operation = store.read_operation(options["operation_id"])
            if options["action"] == "run":
                result = service.run_operation(operation["id"])
            elif options["action"] == "status":
                result = service._public(operation)
            else:
                actor = service._runner_actor(operation)
                result = service.recover_operation(operation["id"], actor, options["action"])
            self.stdout.write(json.dumps(result, indent=2, default=str))
        except service.TransferError as error:
            raise CommandError(str(error)) from error
