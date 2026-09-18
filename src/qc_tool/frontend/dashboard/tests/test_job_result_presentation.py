"""Presentation contracts for terminal jobs without worker result files."""

from datetime import timedelta
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import CONFIG, JOB_ERROR, compose_job_dir
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.jobs.serializers import (
    MISSING_RESULT_ERROR_MESSAGE,
)


class MissingWorkerResultPresentationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="result-owner",
            password="test-password",
        )
        self.delivery = Delivery.objects.create(
            user=self.user,
            filename="delivery.zip",
            size_bytes=128,
            product_ident="general_raster",
            product_description="General raster checks",
        )
        finished_at = timezone.now()
        self.job = Job.objects.create(
            delivery=self.delivery,
            date_started=finished_at - timedelta(seconds=5),
            date_finished=finished_at,
            job_status=JOB_ERROR,
            product_ident="general_raster",
            product_description="General raster checks",
        )
        self.client.force_login(self.user)
        UserProductGrant.objects.create(user=self.user, product_ident="general_raster")

    @patch(
        "qc_tool.frontend.dashboard.views.jobs.results."
        "compile_job_report_data",
        return_value={
            "job_uuid": None,
            "description": None,
            "product_ident": None,
            "filename": None,
            "reference_year": None,
            "job_start_date": None,
            "job_finish_date": None,
            "status": None,
            "error_message": None,
            "steps": [],
        },
    )
    def test_result_page_uses_persisted_facts_and_actionable_error(self, _compile):
        response = self.client.get(
            reverse("show_result", args=(self.job.job_uuid,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delivery.zip")
        self.assertContains(response, "General raster checks")
        self.assertContains(response, "QC job error")
        self.assertContains(response, MISSING_RESULT_ERROR_MESSAGE)
        self.assertNotContains(response, "SYSTEM ERROR: None")

    @patch(
        "qc_tool.frontend.dashboard.views.jobs.results."
        "compile_job_report_data",
        return_value={"status": None, "error_message": None, "steps": []},
    )
    def test_json_report_has_the_same_safe_fallback_contract(self, _compile):
        response = self.client.get(
            reverse("job_report_json", args=(self.job.job_uuid,))
        )

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["status"], JOB_ERROR)
        self.assertEqual(report["filename"], "delivery.zip")
        self.assertEqual(report["product_ident"], "general_raster")
        self.assertEqual(report["error_message"], MISSING_RESULT_ERROR_MESSAGE)
        self.assertIsNotNone(report["job_start_date"])
        self.assertIsNotNone(report["job_finish_date"])

    @patch(
        "qc_tool.frontend.dashboard.views.jobs.results.compile_job_report_data",
        return_value={"status": "error", "steps": [{
            "step_nr": 1, "check_ident": "geometry", "description": "Geometry validity",
            "layers": ["parcels"], "status": "failed", "messages": ["Invalid boundary"],
            "attachment_filenames": [],
        }]},
    )
    def test_check_table_uses_shared_exports_while_report_downloads_remain_available(self, _compile):
        response = self.client.get(reverse("show_result", args=(self.job.job_uuid,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="tbl-results"')
        self.assertContains(response, 'id="qc-table-export-config"')
        self.assertContains(response, "dashboard/js/features/jobs/result/table.js")
        self.assertNotContains(response, 'data-toggle="table"')
        self.assertContains(response, "Invalid boundary")
        for route in ("job_report_json", "job_combined_log"):
            self.assertContains(response, reverse(route, args=(self.job.job_uuid,)))
        self.assertNotContains(response, reverse("job_report_pdf", args=(self.job.job_uuid,)))


class HistoricalSpecificationResultTests(TestCase):
    """Render actual worker artifacts from uploaded, versioned specifications."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        catalog = root / "catalog"
        catalog.mkdir()
        # The catalog may have changed since this job ran. Reports must keep
        # using the historical specification saved alongside its results.
        (catalog / "example.json").write_text(json.dumps({
            "description": "New catalog specification", "steps": [],
        }))
        config = patch.dict(CONFIG, {"work_dir": root, "product_dirs": [catalog]})
        config.start()
        self.addCleanup(config.stop)
        self.user = get_user_model().objects.create_user(username="historical-result-owner")
        UserProductGrant.objects.create(user=self.user, product_ident="example")
        delivery = Delivery.objects.create(
            user=self.user, filename="delivery.zip", size_bytes=128,
            product_ident="example", product_description="Historical specification",
        )
        self.job = Job.objects.create(
            delivery=delivery, product_ident="example",
            product_description="Historical specification", job_status="failed",
            date_finished=timezone.now(),
        )
        job_directory = compose_job_dir(self.job.pk)
        job_directory.mkdir()
        snapshot = json.dumps({
            "description": "Historical specification",
            "steps": [
                {"check_ident": "qc_tool.vector.naming", "required": True},
                {"check_ident": "qc_tool.vector.attribute", "required": False},
            ],
        }).encode("utf-8")
        (job_directory / (hashlib.sha256(snapshot).hexdigest() + ".json")).write_bytes(snapshot)
        (job_directory / "result.json").write_text(json.dumps({
            "job_uuid": str(self.job.pk), "product_ident": "example",
            "status": "failed", "filename": "delivery.zip",
            "steps": [{
                "check_ident": "qc_tool.vector.naming", "status": "aborted",
                "messages": ["The layer name does not match naming convention."],
                "attachment_filenames": [],
            }],
        }))
        self.client.force_login(self.user)

    def assert_historical_report(self, report):
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["description"], "Historical specification")
        self.assertEqual(len(report["steps"]), 2)
        self.assertEqual(report["steps"][0]["status"], "aborted")
        self.assertEqual(report["steps"][0]["messages"], [
            "The layer name does not match naming convention.",
        ])
        self.assertIsNone(report["steps"][1]["status"])

    def test_html_report_displays_failure_from_digest_named_snapshot(self):
        response = self.client.get(reverse("show_result", args=(self.job.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historical specification")
        self.assertContains(response, "QC job stopped early")
        self.assertContains(response, "The layer name does not match naming convention.")
        self.assertContains(response, "Not run")
        self.assertNotContains(response, "Attribute table is composed of prescribed attributes.")
        self.assertNotContains(response, "New catalog specification")

        all_checks = self.client.get(reverse("show_result", args=(self.job.pk,)), {"checks": "all"})
        self.assertContains(all_checks, "Not started")
        self.assertContains(all_checks, "Attribute table is composed of prescribed attributes.")

    def test_json_download_uses_the_same_historical_snapshot(self):
        response = self.client.get(reverse("job_report_json", args=(self.job.pk,)))

        self.assertEqual(response.status_code, 200)
        self.assert_historical_report(response.json())

    def test_api_report_uses_the_same_historical_snapshot(self):
        token = issue_personal_access_token(self.user, "Historical report test")
        response = self.client.get(
            reverse("api_job_result", args=(self.job.pk,)),
            HTTP_AUTHORIZATION=f"Bearer {token.raw_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assert_historical_report(response.json()["data"])
