"""Regression coverage for UUID objects supplied by Django URL converters."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from qc_tool.common import CONFIG
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


class JobUUIDRouteTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="uuid-route-owner",
        )
        UserProductGrant.objects.create(user=self.owner, product_ident="test-product")
        self.delivery = Delivery.objects.create(
            user=self.owner,
            filename="delivery.zip",
            size_bytes=1,
            product_ident="test-product",
            product_description="Test product",
        )
        self.job = Job.objects.create(
            delivery=self.delivery,
            product_ident="test-product",
            product_description="Test product",
        )
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.work_dir = Path(self.temporary_directory.name)

    def product_definition(self):
        return {
            "product_ident": "test-product",
            "description": "Test product",
            "steps": [],
        }

    def test_session_result_routes_accept_django_uuid_objects(self):
        self.client.force_login(self.owner)

        with (
            patch.dict(CONFIG, {"work_dir": self.work_dir}),
            patch(
                "qc_tool.common.load_product_definition",
                return_value=self.product_definition(),
            ),
        ):
            result_page = self.client.get(
                reverse("show_result", args=(self.job.job_uuid,)),
            )
            json_report = self.client.get(
                reverse("job_report_json", args=(self.job.job_uuid,)),
            )
            combined_log = self.client.get(
                reverse("job_combined_log", args=(self.job.job_uuid,)),
            )

        self.assertEqual(result_page.status_code, 200)
        self.assertEqual(json_report.status_code, 200)
        self.assertEqual(
            json_report.json()["job_uuid"],
            str(self.job.job_uuid),
        )
        self.assertEqual(combined_log.status_code, 200)
        self.assertContains(combined_log, "stdout log: no data.")
        self.assertContains(combined_log, "job log: no data.")

    def test_api_result_accepts_django_uuid_objects(self):
        authorization = "Bearer {}".format(
            issue_personal_access_token(
                self.owner,
                "UUID route test",
            ).raw_token,
        )

        with (
            patch.dict(CONFIG, {"work_dir": self.work_dir}),
            patch(
                "qc_tool.common.load_product_definition",
                return_value=self.product_definition(),
            ),
        ):
            response = self.client.get(
                reverse("api_job_result", args=(self.job.job_uuid,)),
                HTTP_AUTHORIZATION=authorization,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["data"]["job_uuid"],
            str(self.job.job_uuid),
        )
