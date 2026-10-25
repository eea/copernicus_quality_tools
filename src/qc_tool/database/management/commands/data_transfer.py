"""Dedicated transfer runner and recovery, independent of QC workers."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from qc_tool.database.transfers import service, store


class Command(BaseCommand):
    help = "Stage a local package, run/recover a transfer, or release a completed export payload."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("run", "status", "retry", "cancel", "stage-file", "release-package"))
        parser.add_argument("operation_id", help="Operation UUID, or a package path for stage-file.")
        parser.add_argument("--actor", help="Active administrator username; required for staging or releasing packages.")
        parser.add_argument("--records-only", action="store_true", help="Stage records without restoring included files.")

    def handle(self, *args, **options):
        try:
            action = options["action"]
            if options["records_only"] and action != "stage-file":
                raise CommandError("--records-only applies only to stage-file.")
            if action in {"stage-file", "release-package"}:
                if not options["actor"]:
                    raise CommandError("--actor must name the active QC Tool administrator authorizing this action.")
                try:
                    actor = get_user_model().objects.get(username=options["actor"])
                except get_user_model().DoesNotExist as error:
                    raise CommandError("Choose an existing active administrator.") from error
                if action == "stage-file":
                    result = service.stage_import_path(options["operation_id"], actor,
                        include_files=False if options["records_only"] else None)
                else:
                    result = service.release_export_package(options["operation_id"], actor)
                self.stdout.write(json.dumps(result, indent=2, default=str))
                return
            operation = store.read_operation(options["operation_id"])
            if action == "run":
                result = service.run_operation(operation["id"])
            elif action == "status":
                result = service._public(operation)
            else:
                actor = service._runner_actor(operation)
                result = service.recover_operation(operation["id"], actor, options["action"])
            self.stdout.write(json.dumps(result, indent=2, default=str))
        except service.TransferError as error:
            raise CommandError(str(error)) from error
