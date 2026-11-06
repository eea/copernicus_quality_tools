"""Inventory or explicitly remove one reviewed abandoned worker scratch tree."""

import json

from django.core.management.base import BaseCommand, CommandError

from qc_tool.common import CONFIG, JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL, JOB_TIMEOUT
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.maintenance import MaintenanceError
from qc_tool.frontend.dashboard.services.maintenance.barrier import ready_barrier
from qc_tool.jobs import normalize_job_uuid
from qc_tool.storage.layout import runtime_paths
from qc_tool.storage.scratch_retention import (
    ScratchRetentionError, inspect_scratch, remove_scratch, validate_scratch_layout,
)


_TERMINAL = {JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL, JOB_TIMEOUT}


class Command(BaseCommand):
    help = "Plan scratch cleanup (default); apply removes one reviewed terminal job's abandoned scratch."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--job", help="Canonical job UUID to inspect or explicitly remove.")
        parser.add_argument("--review-token", help="Exact token returned by the read-only plan.")
        parser.add_argument("--generation", type=int, help="Ready maintenance generation required for apply.")
        parser.add_argument("--older-than-hours", type=float, default=24)

    def handle(self, *args, **options):
        try:
            hours = options["older_than_hours"]
            if not 1 <= hours <= 24 * 3650:
                raise CommandError("Inactivity must be between one hour and ten years.")
            root = validate_scratch_layout(runtime_paths(CONFIG))
            identifier = normalize_job_uuid(options["job"]) if options["job"] else None
            if options["apply"]:
                if not identifier or not options["review_token"] or options["generation"] is None:
                    raise CommandError("Apply requires --job, --review-token and --generation from a reviewed plan and ready maintenance.")
                with ready_barrier(options["generation"]):
                    status = Job.objects.filter(pk=identifier).values_list("job_status", flat=True).first()
                    if status not in _TERMINAL:
                        raise CommandError("Only a recorded terminal job's scratch can be removed. Unknown, waiting and running jobs remain retained.")
                    result = remove_scratch(root, identifier, options["review_token"], minimum_age_seconds=hours * 3600)
                self.stdout.write(json.dumps(result, indent=2))
                return
            items = inspect_scratch(root, minimum_age_seconds=hours * 3600)
            if identifier:
                compact = identifier.replace("-", "")
                items = [item for item in items if item.get("job_uuid") == identifier or item.get("directory") == compact]
            identifiers = [item["job_uuid"] for item in items if item.get("eligible")]
            statuses = dict(Job.objects.filter(pk__in=identifiers).values_list("job_uuid", "job_status"))
            statuses = {str(key): value for key, value in statuses.items()}
            for item in items:
                if item.get("eligible"):
                    item["job_status"] = statuses.get(item["job_uuid"])
                    if item["job_status"] not in _TERMINAL:
                        item.update(eligible=False, reason="Recorded job is unavailable or not terminal.")
                        item.pop("review_token", None)
            self.stdout.write(json.dumps({"mode": "plan", "minimum_inactive_hours": hours, "scratch": items}, indent=2))
        except (ScratchRetentionError, MaintenanceError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
