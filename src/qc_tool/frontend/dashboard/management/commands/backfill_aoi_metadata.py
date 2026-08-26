"""Backfill canonical AOI metadata from historical QC result documents."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from qc_tool.frontend.dashboard.services.aoi import backfill_aoi_metadata


class Command(BaseCommand):
    help = (
        "Backfill null Job.aoi_code_submitted values from terminal result.json "
        "files and refresh Delivery submitted-AOI projections."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Rows processed per batch (1-1000; default: 100).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional maximum number of historical jobs to inspect.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Inspect result files and report changes without writing.",
        )

    def handle(self, *args, **options):
        try:
            result = backfill_aoi_metadata(
                batch_size=options["batch_size"],
                limit=options["limit"],
                dry_run=options["dry_run"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        mode = "Dry run" if options["dry_run"] else "Backfill"
        self.stdout.write(
            self.style.SUCCESS(
                "{} complete: scanned={}, candidates={}, updated={}, "
                "projected={}, unreadable={}, unavailable={}.".format(
                    mode,
                    result.scanned_jobs,
                    result.candidate_jobs,
                    result.updated_jobs,
                    result.projected_deliveries,
                    result.unreadable_results,
                    result.unavailable_metadata,
                )
            )
        )
