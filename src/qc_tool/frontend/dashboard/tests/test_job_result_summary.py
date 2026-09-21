"""Historical run summaries, actionable check filters and permitted actions."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone as datetime_timezone
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import (
    JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL, JOB_RUNNING,
    JOB_TIMEOUT, JOB_WAITING,
)
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductUnit,
)
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.jobs.result_presentation import build_result_presentation


class JobResultSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="result-summary-owner")
        cls.other = get_user_model().objects.create_user(username="result-summary-other")
        cls.admin = get_user_model().objects.create_superuser(username="result-summary-admin", password="test")
        for user in (cls.owner, cls.other):
            UserProductGrant.objects.create(user=user, product_ident="historical")
        cls.product = Product.objects.create(ident="historical", name="Current product name")
        cls.release = ProductRelease.objects.create(
            product=cls.product, release_key="v1", revision=1,
            catalog_digest="a" * 64, is_current=True,
        )
        cls.unit = ProductUnit.objects.create(
            product_release=cls.release, product_unit_code="CZ", provenance="manifest",
        )

    def setUp(self):
        self.delivery = Delivery.objects.create(
            user=self.owner, filename="historical.zip", product_ident="historical", size_bytes=100,
            product_description="Current delivery description",
        )
        self.job = Job.objects.create(
            delivery=self.delivery, job_status=JOB_FAILED, product_ident="historical",
            product_description="Historical job specification", product_release=self.release,
            product_unit_code="CZ", date_started=timezone.now() - timedelta(seconds=20),
            date_finished=timezone.now(),
        )
        self.access = access_for(self.owner)
        self.report = {
            "filename": self.delivery.filename, "description": "Historical report specification",
            "steps": [
                {"step_nr": 1, "check_ident": "qc_tool.vector.unzip", "status": "ok"},
                {"step_nr": 2, "check_ident": "qc_tool.vector.naming_convention", "status": "aborted", "messages": ["Unexpected layer name."]},
                {"check_ident": "qc_tool.vector.geometry", "status": None},
                {"check_ident": "qc_tool.vector.attributes", "status": "skipped"},
            ],
        }
        pdf_patch = patch(
            "qc_tool.frontend.dashboard.services.jobs.result_presentation.open_job_report",
            side_effect=ArtifactUnavailable,
        )
        self.open_pdf = pdf_patch.start()
        self.addCleanup(pdf_patch.stop)

    def present(self, **kwargs):
        return build_result_presentation(self.job, self.report, self.access, **kwargs)

    def test_default_filter_focuses_problems_and_preserves_report(self):
        original = deepcopy(self.report)
        result = self.present()
        self.assertEqual(result["counters"], {"total": 4, "passed": 1, "attention": 1, "not_run": 2, "in_progress": 0})
        self.assertEqual(result["selected_filter"], "attention")
        self.assertEqual([step["title"] for step in result["steps"]], ["Naming convention"])
        self.assertEqual(result["steps"][0]["display_ident"], "vector.naming_convention")
        self.assertEqual(result["steps"][0]["status_label"], "Stopped early")
        self.assertEqual([tab["key"] for tab in result["filters"]], ["all", "attention", "passed", "not_run"])
        self.assertEqual(sum(tab["active"] for tab in result["filters"]), 1)
        self.assertEqual(result["outcome"]["title"], "QC job stopped early")
        self.assertIn("not validated", result["outcome"]["message"])
        self.assertEqual(self.report, original)

    def test_all_and_not_run_filters_keep_execution_order_and_step_numbers(self):
        result = self.present(selected_filter="all")
        self.assertEqual([step["number"] for step in result["steps"]], [1, 2, 3, 4])
        result = self.present(selected_filter="not_run")
        self.assertEqual([step["status_label"] for step in result["steps"]], ["Not started", "Skipped"])
        tab = next(tab for tab in result["filters"] if tab["active"])
        self.assertEqual(tab["url"], "?checks=not_run#job-result-checks")

    def test_unknown_and_empty_filters_fall_back_to_all(self):
        for value in ("unknown", "in_progress"):
            with self.subTest(value=value):
                self.assertEqual(self.present(selected_filter=value)["selected_filter"], "all")

    def test_no_issues_defaults_to_all_and_unknown_check_status_needs_attention(self):
        self.report["steps"] = [{"check_ident": "raster.statistics", "status": "ok"}]
        self.assertEqual(self.present()["selected_filter"], "all")
        self.report["steps"][0]["status"] = "unrecognized"
        result = self.present()
        self.assertEqual(result["counters"]["attention"], 1)
        self.assertEqual(result["steps"][0]["status_label"], "Unknown result")

    def test_status_labels_distinguish_all_job_outcomes(self):
        self.report["steps"] = []
        expected = {
            JOB_OK: ("Passed", "QC passed"), JOB_FAILED: ("Failed", "QC failed"),
            JOB_PARTIAL: ("Partially checked", "QC is incomplete"),
            JOB_ERROR: ("Job error", "QC job error"), JOB_RUNNING: ("In progress", "QC is running"),
            JOB_WAITING: ("In queue", "QC is queued"), JOB_TIMEOUT: ("Timed out", "QC timed out"),
            JOB_LOST: ("Worker unavailable", "QC worker is unavailable"),
        }
        for status, (label, title) in expected.items():
            with self.subTest(status=status):
                self.job.job_status = status
                result = self.present()
                self.assertEqual(result["summary"]["status"]["label"], label)
                self.assertEqual(result["outcome"]["title"], title)

    def test_summary_uses_selected_job_and_historical_specification(self):
        Job.objects.create(delivery=self.delivery, job_status=JOB_OK, product_ident="newer")
        result = self.present()
        self.assertEqual(result["summary"]["status"]["value"], JOB_FAILED)
        self.assertEqual(result["summary"]["description"], "Historical report specification")
        self.assertEqual(result["summary"]["description_url"], reverse("product_detail", args=("historical",)))
        self.report.pop("description")
        self.assertEqual(self.present()["summary"]["description"], "Historical job specification")

    def test_completed_worker_report_takes_precedence_over_stale_running_status(self):
        self.job.job_status = JOB_RUNNING
        self.report["status"] = JOB_FAILED
        result = self.present()
        self.assertEqual(result["summary"]["status"]["value"], JOB_FAILED)
        self.assertEqual(result["outcome"]["title"], "QC job stopped early")

    def test_report_dates_are_parsed_and_duration_is_readable(self):
        self.report.update(job_start_date="2024-05-03T10:20:00Z", job_finish_date="2024-05-03T10:21:05Z")
        facts = {fact["label"]: fact for fact in self.present()["summary"]["facts"]}
        self.assertEqual(facts["Started"]["datetime"], datetime(2024, 5, 3, 10, 20, tzinfo=datetime_timezone.utc))
        self.assertEqual(facts["Started"]["datetime"].hour, 12)
        self.assertEqual(facts["Started"]["datetime"].tzname(), "CEST")
        self.assertEqual(facts["Duration"]["value"], "1 min 5 sec")
        self.assertEqual(facts["Product unit"]["value"], "CZ")
        self.report["job_start_date"] = "invalid"
        facts = {fact["label"]: fact for fact in self.present()["summary"]["facts"]}
        self.assertEqual(facts["Started"]["datetime"].replace(tzinfo=None), self.job.date_started)
        self.assertNotIn("Duration", facts)

    def test_pdf_link_requires_openable_report_and_closes_file(self):
        self.assertFalse(self.present()["can_download_pdf"])
        artifact = BytesIO(b"report")
        self.open_pdf.side_effect = None
        self.open_pdf.return_value = (artifact, "report.pdf")
        self.assertTrue(self.present()["can_download_pdf"])
        self.assertTrue(artifact.closed)

    def test_owner_and_admin_can_open_rerun_setup_but_other_user_cannot(self):
        for user in (self.owner, self.admin):
            result = build_result_presentation(self.job, self.report, access_for(user))
            self.assertEqual(result["summary"]["action"]["url"], f"{reverse('setup_job')}?deliveries={self.delivery.pk}")
        self.access = access_for(self.other)
        self.assertIsNone(self.present()["summary"]["action"])

    def test_rerun_requires_permission_and_delivery_assignment(self):
        self.access = replace(self.access, permissions=self.access.permissions - {AccountPermission.RUN_QC})
        self.assertIsNone(self.present()["summary"]["action"])
        self.access = replace(access_for(self.owner), product_idents=frozenset())
        self.assertIsNone(self.present()["summary"]["action"])

    def test_deleted_submitted_and_active_deliveries_have_no_rerun_action(self):
        self.delivery.is_deleted = True
        self.assertIsNone(self.present()["summary"]["action"])
        self.delivery.is_deleted = False
        self.delivery.date_submitted = timezone.now()
        self.assertIsNone(self.present()["summary"]["action"])
        self.delivery.date_submitted = None
        for status in (JOB_RUNNING, JOB_WAITING):
            active = Job.objects.create(delivery=self.delivery, job_status=status, product_ident="historical")
            self.assertIsNone(self.present()["summary"]["action"])
            active.delete()

    def test_unpublished_submission_reservation_blocks_rerun(self):
        DeliverySubmission.objects.create(
            delivery=self.delivery, job=self.job, product_release=self.release,
            product_unit=self.unit, product_unit_code="CZ", verified_product_unit_code="CZ",
            submitted_by=self.owner, submitted_by_username=self.owner.username,
            request_channel="browser", review_state="pending", publication_state="pending",
            artifact_key="published/historical.zip", artifact_digest="a" * 64, input_digest="b" * 64,
        )
        self.assertIsNone(self.present()["summary"]["action"])

    def test_optional_columns_describe_only_selected_checks(self):
        self.report["steps"][0].update(layers=["parcels"], attachment_filenames=["counts.csv"])
        self.assertFalse(self.present()["has_layers"])
        self.assertFalse(self.present()["has_attachments"])
        result = self.present(selected_filter="passed")
        self.assertTrue(result["has_layers"])
        self.assertTrue(result["has_attachments"])

    def test_empty_report_has_all_filter_and_no_spurious_results(self):
        self.report["steps"] = []
        result = self.present()
        self.assertEqual(result["steps"], [])
        self.assertEqual(result["counters"]["total"], 0)
        self.assertEqual([tab["key"] for tab in result["filters"]], ["all"])
