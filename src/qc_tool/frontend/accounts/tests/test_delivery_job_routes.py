"""Compatibility contracts for delivery-owned QC job pages.

Job history and rendered QC results belong to the Deliveries workspace.  The
named routes are the source of truth for new links, while the former top-level
paths remain one-hop compatibility redirects for bookmarks and notifications.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from qc_tool.common import CONFIG
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


class DeliveryJobRouteTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="delivery-job-route-owner",
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
        self.client.force_login(self.owner)

        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.work_dir = Path(self.temporary_directory.name)

    def product_definition(self):
        return {
            "product_ident": "test-product",
            "description": "Test product",
            "steps": [],
        }

    @property
    def canonical_history_url(self):
        return "/deliveries/jobs/{}/".format(self.delivery.pk)

    @property
    def canonical_result_url(self):
        return "/deliveries/job-result/{}/".format(self.job.job_uuid)

    def test_named_job_routes_are_nested_under_deliveries(self):
        self.assertEqual(
            reverse("job_history", args=(self.delivery.pk,)),
            self.canonical_history_url,
        )
        self.assertEqual(
            reverse("show_result", args=(self.job.job_uuid,)),
            self.canonical_result_url,
        )

    def test_legacy_job_history_path_redirects_to_canonical_delivery_path(self):
        legacy_url = "/job_history/{}/".format(self.delivery.pk)

        response = self.client.get(legacy_url)

        self.assertIn(response.status_code, (301, 302, 307, 308))
        self.assertEqual(response["Location"], self.canonical_history_url)
        self.assertNotEqual(response["Location"], legacy_url)

    def test_interim_delivery_job_history_path_redirects_to_canonical_path(self):
        interim_url = "/deliveries/job_history/{}/".format(self.delivery.pk)

        response = self.client.get(interim_url)

        self.assertIn(response.status_code, (301, 302, 307, 308))
        self.assertEqual(response["Location"], self.canonical_history_url)
        self.assertNotEqual(response["Location"], interim_url)

    def test_legacy_result_path_redirects_to_canonical_delivery_path(self):
        legacy_url = "/result/{}".format(self.job.job_uuid)

        response = self.client.get(legacy_url)

        self.assertIn(response.status_code, (301, 302, 307, 308))
        self.assertEqual(response["Location"], self.canonical_result_url)
        self.assertNotEqual(response["Location"], legacy_url)

    def test_interim_delivery_result_path_redirects_to_canonical_path(self):
        interim_url = "/deliveries/result/{}".format(self.job.job_uuid)

        response = self.client.get(interim_url)

        self.assertIn(response.status_code, (301, 302, 307, 308))
        self.assertEqual(response["Location"], self.canonical_result_url)
        self.assertNotEqual(response["Location"], interim_url)

    def test_canonical_delivery_job_paths_render_without_redirecting_back(self):
        history_response = self.client.get(self.canonical_history_url)

        with (
            patch.dict(CONFIG, {"work_dir": self.work_dir}),
            patch(
                "qc_tool.common.load_product_definition",
                return_value=self.product_definition(),
            ),
        ):
            result_response = self.client.get(self.canonical_result_url)

        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(result_response.status_code, 200)
        self.assertNotIn("Location", history_response)
        self.assertNotIn("Location", result_response)
