"""Unavailable boundaries block all QC entry points before any job is queued."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.common import CONFIG
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services.jobs.prerequisites import (
    JobPrerequisiteUnavailable, require_job_prerequisites,
)
from .catalog_fixtures import managed_definition


@override_settings(MAINTENANCE_MODE=False)
class JobPrerequisiteTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.boundaries = self.root / "boundaries"
        self.boundaries.mkdir()
        self.document = {"description": "Example", "steps": []}
        (self.root / "product.json").write_text(json.dumps(self.document))
        self.enterContext(patch.dict(CONFIG, boundary_dir=self.boundaries, product_dirs=[self.root]))
        snapshot = managed_definition("product", document=self.document)
        self.enterContext(patch(
            "qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot",
            return_value=snapshot,
        ))
        self.admin = get_user_model().objects.create_superuser(username="prerequisite-admin", password="test-only")
        self.user = get_user_model().objects.create_user(username="prerequisite-owner")
        UserProductGrant.objects.create(user=self.user, product_ident="product")
        self.delivery = Delivery.objects.create(user=self.admin, filename="product_delivery.zip", size_bytes=1)
        self.client.force_login(self.admin)

    def activate_fixture(self):
        for name in ("raster", "vector"):
            (self.boundaries / name).mkdir()

    def test_direct_creation_refuses_missing_package_without_job_or_projection_changes(self):
        before = self.delivery.product_ident
        with self.assertRaises(JobPrerequisiteUnavailable) as caught:
            self.delivery.create_job("product", "", requested_by=self.admin, account_access=access_for(self.admin))
        self.assertEqual(caught.exception.code, "boundary_generation_unavailable")
        self.assertIn("Admin → Boundaries", str(caught.exception))
        self.assertNotIn(str(self.boundaries), str(caught.exception))
        self.assertFalse(Job.objects.exists())
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.product_ident, before)

    def test_complete_generation_is_resolved_and_allows_creation(self):
        self.activate_fixture()
        self.assertEqual(require_job_prerequisites().generation_id, "legacy-unmanaged")
        self.delivery.create_job("product", "", requested_by=self.admin, account_access=access_for(self.admin))
        self.assertEqual(Job.objects.count(), 1)

    def test_setup_blocks_run_and_offers_boundary_management_to_administrator(self):
        response = self.client.get(reverse("setup_job"), {"deliveries": self.delivery.pk})
        self.assertContains(response, "QC setup needs administrator attention", status_code=503)
        self.assertContains(response, reverse("boundaries"), status_code=503)
        self.assertContains(response, "<fieldset disabled>", status_code=503)
        self.assertFalse(Job.objects.exists())

    def test_setup_tells_ordinary_user_to_contact_admin_without_admin_destination(self):
        self.delivery.user = self.user
        self.delivery.save(update_fields=("user",))
        self.client.force_login(self.user)
        response = self.client.get(reverse("setup_job"), {"deliveries": self.delivery.pk})
        self.assertContains(response, "Contact an administrator", status_code=503)
        self.assertNotContains(response, reverse("boundaries"), status_code=503)

    def test_browser_and_api_cannot_bypass_boundary_preflight(self):
        browser = self.client.post(reverse("create_job"), {
            "delivery_ids": str(self.delivery.pk), "product_ident": "product", "skip_steps": "",
        })
        issued = issue_personal_access_token(self.admin, "Prerequisite test")
        api = self.client.post(reverse("api_create_job"), {
            "delivery_id": self.delivery.pk, "product_ident": "product",
        }, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {issued.raw_token}")
        for response in (browser, api):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["code"], "boundary_generation_unavailable")
        self.assertFalse(Job.objects.exists())

    def test_unsafe_activation_pointer_is_not_used_as_ready(self):
        (self.boundaries / ".boundary-current").symlink_to("/outside")
        with self.assertRaises(JobPrerequisiteUnavailable) as caught:
            require_job_prerequisites()
        self.assertEqual(caught.exception.code, "boundary_package_configuration_error")
