"""Presentation contracts for terminal jobs without worker result files."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_ERROR
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
        self.assertContains(response, "QC job error:")
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
