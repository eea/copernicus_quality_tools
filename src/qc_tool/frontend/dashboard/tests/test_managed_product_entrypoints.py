"""Bundled definitions become available only through a managed catalog entry."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

import qc_tool.common as common
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.dashboard.models import Delivery, Job, QcDefinition
from qc_tool.frontend.dashboard.services.products.identification import guess_product_ident
from qc_tool.frontend.dashboard.services.uploads.access import require_upload_product
from qc_tool.frontend.dashboard.services.uploads.resumable import ResumableUploadError
from qc_tool.frontend.dashboard.views.api_access.products import api_product_info, api_product_list
from qc_tool.frontend.dashboard.views.jobs.setup import _product_options

from .catalog_fixtures import managed_definition


@override_settings(MAINTENANCE_MODE=False)
class ManagedProductEntrypointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="catalog-admin", email="admin@example.test", password="test-only",
        )
        self.client.force_login(self.user)
        self.access = access_for(self.user)
        directory = self.enterContext(TemporaryDirectory())
        self.root = Path(directory)
        self.document = {"description": "Bundled example", "steps": []}
        (self.root / "bundled.json").write_text(json.dumps(self.document))
        self.enterContext(patch.dict(common.CONFIG, product_dirs=[self.root], work_dir=self.root / "work"))

    def api_request(self):
        request = RequestFactory().get("/api/product-list")
        request.api_access = self.access
        return request

    def test_empty_catalog_has_no_choices_even_with_a_bundled_file(self):
        self.assertIn("bundled", common.get_product_descriptions())
        self.assertEqual(self.client.get(reverse("product_list_json")).json(), {"product_list": []})
        self.assertEqual(json.loads(api_product_list(self.api_request()).content), {"products": []})
        self.assertEqual(_product_options(self.access), [])
        self.assertIsNone(guess_product_ident(Path("bundled_delivery.zip")))

        upload = self.client.get(reverse("file_upload"))
        self.assertContains(upload, "Upload a product specification JSON before adding deliveries.")
        self.assertContains(upload, reverse("product_upload"))
        self.assertNotContains(upload, 'id="delivery-upload-file"')

    def test_admin_cannot_access_bundled_metadata_or_start_qc_without_catalog(self):
        for route in ("product_definition_json", "job_info_json"):
            self.assertEqual(self.client.get(reverse(route, args=("bundled",))).status_code, 404)
        self.assertEqual(api_product_info(self.api_request(), "bundled").status_code, 404)
        delivery = Delivery.objects.create(user=self.user, filename="bundled.zip", size_bytes=1)
        with self.assertRaisesMessage(ValueError, "administrator must upload"):
            delivery.create_job("bundled", "", account_access=self.access)
        self.assertFalse(Job.objects.exists())
        self.assertFalse(QcDefinition.objects.exists())
        with self.assertRaises(ResumableUploadError):
            require_upload_product(self.access, None)

    def test_managed_current_definition_enables_the_same_entrypoints(self):
        managed_definition("bundled", document=self.document)
        self.assertContains(self.client.get(reverse("file_upload")), 'id="delivery-upload-file"')
        self.assertEqual(len(self.client.get(reverse("product_list_json")).json()["product_list"]), 1)
        self.assertEqual(api_product_info(self.api_request(), "bundled").status_code, 200)
        self.assertEqual(guess_product_ident(Path("bundled_delivery.zip")), "bundled")
        require_upload_product(self.access, "bundled")
        require_upload_product(self.access, None)
        delivery = Delivery.objects.create(user=self.user, filename="bundled.zip", size_bytes=1)
        delivery.create_job("bundled", "", account_access=self.access)
        self.assertEqual(Job.objects.count(), 1)

    def test_archiving_a_managed_product_removes_it_from_new_deliveries_and_jobs(self):
        _definition, release = managed_definition("bundled", document=self.document)
        release.product.is_active = False
        release.product.save(update_fields=("is_active",))
        self.assertEqual(_product_options(self.access), [])
        with self.assertRaises(ResumableUploadError):
            require_upload_product(self.access, "bundled")

    def test_changed_executable_bytes_cannot_create_a_job_or_an_orphan_definition(self):
        definition, release = managed_definition("bundled", document=self.document)
        changed_document = {**self.document, "description": "Unreviewed file change"}
        (self.root / "bundled.json").write_text(json.dumps(changed_document))
        delivery = Delivery.objects.create(user=self.user, filename="bundled.zip", size_bytes=1)

        with self.assertRaisesMessage(ValueError, "awaiting activation"):
            delivery.create_job("bundled", "", account_access=self.access)

        self.assertFalse(Job.objects.exists())
        self.assertEqual(list(QcDefinition.objects.values_list("pk", flat=True)), [definition.pk])
        definition.refresh_from_db()
        self.assertEqual(definition.document, self.document)
        self.assertEqual(release.definition_links.get().qc_definition_id, definition.pk)
        delivery.refresh_from_db()
        self.assertIsNone(delivery.product_ident)
