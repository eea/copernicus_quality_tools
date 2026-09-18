from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.dashboard.services.aoi import AoiResultUnavailable
from qc_tool.frontend.dashboard.services.aoi import backfill_aoi_metadata
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.jobs import serialize_job_report
from qc_tool.frontend.dashboard.views import query_deliveries


class AoiPersistenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="aoi-owner",
            password="test-password",
        )
        self.delivery = Delivery.objects.create(
            user=self.user,
            filename="delivery.zip",
            size_bytes=1024,
        )

    def create_job(self, *, created_at=None, aoi_code=None, job_uuid=None):
        values = {
            "delivery": self.delivery,
            "date_created": created_at or timezone.now(),
            "job_status": JOB_RUNNING,
            "product_ident": "product",
            "product_description": "Product",
            "aoi_code": aoi_code,
        }
        if job_uuid is not None:
            values["job_uuid"] = job_uuid
        return Job.objects.create(**values)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document",
        return_value={"aoi_code": "EE003LX"},
    )
    def test_terminal_result_updates_job_and_delivery_canonically(self, loader):
        job = self.create_job()

        job.update_status(JOB_OK)
        job.refresh_from_db()
        self.delivery.refresh_from_db()

        loader.assert_called_once_with(job.job_uuid)
        self.assertEqual(job.aoi_code, "ee003l")
        self.assertEqual(job.aoi_code_submitted, "ee003l")
        self.assertEqual(self.delivery.aoi_code, "ee003l")
        self.assertEqual(self.delivery.aoi_code_submitted, "ee003l")
        self.assertIsNotNone(job.date_finished)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document",
        return_value={"status": "ok"},
    )
    def test_success_without_one_verified_aoi_becomes_job_error(self, _):
        job = self.create_job()

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.aoi.lifecycle",
            level="ERROR",
        ):
            job.update_status(JOB_OK)
        job.refresh_from_db()

        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertIsNone(job.aoi_code_submitted)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document",
        return_value={"aoi_code": "EE002L1"},
    )
    def test_later_job_cannot_replace_the_zip_aoi_identity(self, _):
        self.delivery.aoi_code_submitted = "ee001l"
        self.delivery.save(update_fields=("aoi_code_submitted",))
        job = self.create_job()

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.aoi.lifecycle",
            level="ERROR",
        ):
            job.update_status(JOB_OK)
        job.refresh_from_db()
        self.delivery.refresh_from_db()

        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertEqual(job.aoi_code_submitted, "ee002l")
        self.assertEqual(self.delivery.aoi_code_submitted, "ee001l")

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document"
    )
    def test_running_status_does_not_read_result_metadata(self, loader):
        job = self.create_job(aoi_code="existing")

        job.update_status(JOB_RUNNING)
        job.refresh_from_db()

        loader.assert_not_called()
        self.assertEqual(job.aoi_code, "existing")
        self.assertIsNone(job.date_finished)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document",
        return_value={"aoi_code": "EE003L1", "hash": "a" * 64},
    )
    def test_terminal_job_metadata_cannot_be_replaced(self, loader):
        job = self.create_job()
        job.update_status(JOB_OK)
        job.refresh_from_db()
        original_finished = job.date_finished
        original_result_digest = job.result_sha256

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.aoi.lifecycle",
            level="WARNING",
        ):
            job.update_status(JOB_FAILED)
        job.refresh_from_db()

        self.assertEqual(job.job_status, JOB_OK)
        self.assertEqual(job.aoi_code_submitted, "ee003l")
        self.assertEqual(job.input_sha256, "a" * 64)
        self.assertEqual(job.date_finished, original_finished)
        self.assertEqual(job.result_sha256, original_result_digest)
        loader.assert_called_once_with(job.job_uuid)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document",
        side_effect=AoiResultUnavailable,
    )
    def test_unavailable_result_does_not_block_terminal_status(self, _):
        job = self.create_job(aoi_code="existing")

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.aoi.lifecycle",
            level="WARNING",
        ):
            job.update_status(JOB_FAILED)
        job.refresh_from_db()

        self.assertEqual(job.job_status, JOB_FAILED)
        self.assertEqual(job.aoi_code, "existing")
        self.assertIsNotNone(job.date_finished)

    def test_result_update_distinguishes_missing_null_and_malformed(self):
        job = self.create_job(aoi_code="existing")

        self.assertEqual(job.apply_result_metadata({}), [])
        self.assertEqual(job.aoi_code, "existing")
        self.assertEqual(job.apply_result_metadata({"aoi_code": 123}), [])
        self.assertEqual(job.aoi_code, "existing")
        self.assertEqual(
            job.apply_result_metadata({"aoi_code": None}),
            ["aoi_code"],
        )
        self.assertIsNone(job.aoi_code)
        self.assertEqual(
            job.apply_result_metadata({"aoi_code": "EE003L1"}),
            ["aoi_code", "aoi_code_submitted"],
        )
        self.assertEqual(job.aoi_code, "ee003l")
        self.assertEqual(job.aoi_code_submitted, "ee003l")

    @patch(
        "qc_tool.frontend.dashboard.models.find_product_description",
        return_value="New product",
    )
    def test_newer_job_resets_delivery_projection_until_result_exists(self, _):
        older = self.create_job(aoi_code="old-aoi")
        older.job_status = JOB_OK
        older.save(update_fields=("job_status",))
        self.delivery.sync_from_latest_job()

        self.delivery.create_job("new-product", "")
        self.delivery.refresh_from_db()

        self.assertEqual(older.aoi_code, "old-aoi")
        self.assertIsNone(self.delivery.aoi_code)
        self.assertEqual(self.delivery.product_ident, "new-product")

    @patch(
        "qc_tool.frontend.dashboard.models.find_product_description",
        return_value="Product",
    )
    def test_token_deletion_does_not_rewrite_job_provenance(self, _):
        token = PersonalAccessToken.objects.create(
            user=self.user,
            name="QC request token",
            secret_digest="sha256$" + ("b" * 64),
        )
        token_id = token.pk

        self.delivery.create_job(
            "product",
            "",
            requested_by=self.user,
            request_source="api",
            api_token=token,
        )
        token.delete()

        job = Job.objects.get(delivery=self.delivery)
        self.assertEqual(job.requested_by_id, self.user.pk)
        self.assertEqual(job.requested_by_username, self.user.username)
        self.assertEqual(job.request_source, "api")
        self.assertEqual(job.requested_api_token_id, token_id)
        self.assertEqual(job.requested_api_token_name, "QC request token")

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle."
        "load_aoi_result_document",
        return_value={"aoi_code": "old-finished"},
    )
    def test_older_job_finishing_cannot_overwrite_newer_projection(self, _):
        now = timezone.now()
        older = self.create_job(created_at=now - timedelta(hours=1))
        self.create_job(created_at=now, aoi_code="newer")
        self.delivery.sync_from_latest_job()

        older.update_status(JOB_FAILED)
        self.delivery.refresh_from_db()

        self.assertEqual(self.delivery.aoi_code, "newer")

    def test_projection_uses_uuid_as_tie_breaker_for_equal_timestamps(self):
        created_at = timezone.now()
        self.create_job(
            created_at=created_at,
            aoi_code="lower-uuid",
            job_uuid=UUID(int=1),
        )
        self.create_job(
            created_at=created_at,
            aoi_code="higher-uuid",
            job_uuid=UUID(int=2),
        )

        self.delivery.sync_from_latest_job()
        self.delivery.refresh_from_db()

        self.assertEqual(self.delivery.aoi_code, "higher-uuid")

    def test_serializers_expose_only_persisted_canonical_key(self):
        job = self.create_job(aoi_code="canonical")
        job.aoi_code_submitted = "zip-canonical"

        history = serialize_job_history([job])[0]
        report = serialize_job_report(
            {"aoi_code": "stale", "fua_code": "alias"},
            job,
        )

        self.assertEqual(history["aoi_code"], "canonical")
        self.assertEqual(history["aoi_code_submitted"], "zip-canonical")
        self.assertEqual(report["aoi_code"], "canonical")
        self.assertEqual(report["aoi_code_submitted"], "zip-canonical")
        self.assertNotIn("fua_code", history)
        self.assertNotIn("fua_code", report)

    def test_delivery_list_projection_includes_aoi_for_every_row(self):
        self.delivery.aoi_code = "ee003l"
        self.delivery.save(update_fields=("aoi_code",))

        total, rows = query_deliveries(
            self.user,
            limit=10,
            account_access=SimpleNamespace(is_administrator=True),
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["aoi_code"], "ee003l")

    def test_result_page_escapes_reported_aoi_metadata(self):
        markup = '<img src=x onerror="alert(1)">'

        rendered = render_to_string(
            "dashboard/jobs/result.html",
            {
                "delivery": self.delivery,
                "job_report": {
                    "aoi_code": markup,
                    "job_uuid": UUID(int=1),
                    "steps": [],
                },
            },
        )

        self.assertNotIn(markup, rendered)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", rendered)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.backfill."
        "load_aoi_result_document"
    )
    def test_historical_backfill_is_bounded_and_reprojects(self, loader):
        terminal = self.create_job(aoi_code=None)
        terminal.job_status = JOB_OK
        terminal.save(update_fields=("job_status",))
        loader.return_value = {"aoi_code": "DU001A"}

        result = backfill_aoi_metadata(batch_size=1, limit=1)
        terminal.refresh_from_db()
        self.delivery.refresh_from_db()

        self.assertEqual(result.scanned_jobs, 1)
        self.assertEqual(result.candidate_jobs, 1)
        self.assertEqual(result.updated_jobs, 1)
        self.assertEqual(result.projected_deliveries, 1)
        self.assertEqual(terminal.aoi_code, "du001")
        self.assertEqual(self.delivery.aoi_code, "du001")

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.backfill."
        "load_aoi_result_document",
        return_value={"aoi_code": "DU001A"},
    )
    def test_historical_backfill_dry_run_reports_without_writing(self, _):
        terminal = self.create_job(aoi_code=None)
        terminal.job_status = JOB_OK
        terminal.save(update_fields=("job_status",))

        result = backfill_aoi_metadata(batch_size=1, limit=1, dry_run=True)
        terminal.refresh_from_db()
        self.delivery.refresh_from_db()

        self.assertEqual(result.candidate_jobs, 1)
        self.assertEqual(result.updated_jobs, 0)
        self.assertEqual(result.projected_deliveries, 0)
        self.assertIsNone(terminal.aoi_code)
        self.assertIsNone(self.delivery.aoi_code)

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.backfill."
        "load_aoi_result_document",
        return_value={"aoi_code": "EE003L1"},
    )
    def test_historical_backfill_repairs_blank_legacy_values(self, _):
        terminal = self.create_job(aoi_code="")
        terminal.job_status = JOB_OK
        terminal.save(update_fields=("job_status",))

        result = backfill_aoi_metadata(batch_size=1, limit=1)
        terminal.refresh_from_db()

        self.assertEqual(result.updated_jobs, 1)
        self.assertEqual(terminal.aoi_code, "ee003l")
