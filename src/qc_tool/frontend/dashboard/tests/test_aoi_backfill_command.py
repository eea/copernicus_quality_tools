from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class AoiBackfillCommandTests(SimpleTestCase):
    @patch(
        "qc_tool.frontend.dashboard.management.commands."
        "backfill_aoi_metadata.backfill_aoi_metadata"
    )
    def test_dry_run_distinguishes_candidates_from_database_updates(
        self,
        backfill,
    ):
        backfill.return_value = SimpleNamespace(
            scanned_jobs=4,
            candidate_jobs=2,
            updated_jobs=0,
            projected_deliveries=0,
            unreadable_results=1,
            unavailable_metadata=1,
        )
        output = StringIO()

        call_command(
            "backfill_aoi_metadata",
            "--dry-run",
            "--limit=4",
            stdout=output,
        )

        self.assertIn("Dry run complete", output.getvalue())
        self.assertIn("candidates=2", output.getvalue())
        self.assertIn("updated=0", output.getvalue())
        backfill.assert_called_once_with(
            batch_size=100,
            limit=4,
            dry_run=True,
        )
