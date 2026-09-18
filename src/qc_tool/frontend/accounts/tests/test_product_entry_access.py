"""Assigned products constrain browser and API delivery entry points."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import (
    Delivery, Product, ProductRelease, ProductReleaseDefinition, QcDefinition, S3Info,
)
from qc_tool.frontend.dashboard.services.s3 import S3Delivery
from qc_tool.frontend.dashboard.services.tests.test_resumable_uploads import _parameters


@override_settings(MAINTENANCE_MODE=False)
class ProductEntryAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assigned-uploader")
        for ident in ("product-a", "product-b"):
            UserProductGrant.objects.create(user=self.user, product_ident=ident)
        self.authorization = "Bearer " + issue_personal_access_token(self.user, "Uploads").raw_token
        self.client.force_login(self.user)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.media_root = Path(temporary.name)
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root))
        self.descriptions = {ident: ident.title() for ident in ("product-a", "product-b", "product-c")}
        self.enterContext(patch(
            "qc_tool.frontend.dashboard.services.products.identification.get_product_descriptions",
            return_value=self.descriptions,
        ))

    def upload(self, filename="product-a_delivery.zip", **parameters):
        return self.client.post(reverse("resumable_upload"), {
            **_parameters(filename=filename), **parameters,
            "file": SimpleUploadedFile("chunk", b"abcd"),
        })

    def test_browser_uploads_each_assigned_product_and_unclassified_zip(self):
        for filename in ("product-a_delivery.zip", "product-b_delivery.zip", "unknown.zip"):
            with self.subTest(filename=filename):
                response = self.upload(filename)
                self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Delivery.objects.count(), 3)

    def test_unassigned_browser_upload_and_preflight_fail_before_writing_files(self):
        filename = "product-c_delivery.zip"
        preflight = self.client.post(reverse("delivery_upload_check"), {"filenames": [filename]}, content_type="application/json")
        chunk = self.upload(filename)
        probe = self.client.get(reverse("resumable_upload"), _parameters(filename=filename))
        for response in (preflight, chunk, probe):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "product_permission_denied")
        self.assertFalse(Delivery.objects.exists())
        self.assertEqual(list(self.media_root.iterdir()), [])

    def test_account_without_assignments_cannot_upload_even_unclassified_zip(self):
        self.user.product_grants.all().delete()
        page = self.client.get(reverse("file_upload"))
        self.assertContains(page, "No products assigned")
        self.assertContains(page, "Contact an administrator")
        self.assertNotContains(page, 'id="delivery-upload-file"')
        self.assertEqual(self.upload("unknown.zip").status_code, 403)
        self.assertFalse(Delivery.objects.exists())

    def test_revoked_assignment_blocks_existing_upload_receipts(self):
        self.assertEqual(self.upload().status_code, 200)
        self.user.product_grants.filter(product_ident="product-a").delete()
        parameters = _parameters(filename="product-a_delivery.zip")
        self.assertEqual(self.client.get(reverse("resumable_upload"), parameters).status_code, 403)
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_generic_filename_cannot_bypass_overwrite_product_scope(self):
        self.assertEqual(self.upload("unknown.zip").status_code, 200)
        delivery = Delivery.objects.get()
        delivery.product_ident = "product-c"
        delivery.save(update_fields=("product_ident",))
        response = self.upload("unknown.zip", overwrite_delivery_id=delivery.pk, resumableIdentifier="overwrite")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual((self.media_root / self.user.username / "unknown.zip").read_bytes(), b"abcd")

    def test_generic_upload_receipt_respects_its_assigned_product_after_qc(self):
        self.assertEqual(self.upload("unknown.zip").status_code, 200)
        Delivery.objects.update(product_ident="product-c")
        probe = self.client.get(reverse("resumable_upload"), _parameters(filename="unknown.zip"))
        self.assertEqual(probe.status_code, 403)
        self.assertEqual(self.upload("unknown.zip").status_code, 403)
        self.assertEqual(Delivery.objects.count(), 1)

    def register_local(self, filename):
        user_root = self.media_root / self.user.username
        user_root.mkdir(exist_ok=True)
        (user_root / filename).write_bytes(b"archive")
        return self.client.post(reverse("api_register_delivery"), {"uploaded_file": filename},
                                content_type="application/json", HTTP_AUTHORIZATION=self.authorization)

    def test_api_registration_allows_assigned_product_and_rejects_unassigned(self):
        self.assertEqual(self.register_local("product-a_delivery.zip").status_code, 200)
        response = self.register_local("product-c_delivery.zip")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "product_permission_denied")
        self.assertEqual(Delivery.objects.count(), 1)

    def test_api_token_cannot_gain_products_assigned_after_issuance(self):
        UserProductGrant.objects.create(user=self.user, product_ident="product-c")
        self.assertEqual(self.upload("product-c_browser.zip").status_code, 200)
        self.assertEqual(self.register_local("product-c_api.zip").status_code, 403)

    @override_settings(S3_ALLOWED_ENDPOINTS=("https://objects.example.com",))
    def test_s3_registration_rejects_unassigned_product_without_saving_credentials(self):
        with patch("qc_tool.frontend.dashboard.views.api_access.deliveries.inspect_s3_delivery",
                   return_value=S3Delivery(filename="product-c_delivery.zip", size_bytes=4)):
            response = self.client.post(reverse("api_register_delivery_s3"), {
                "host": "https://objects.example.com", "access_key": "key", "secret_key": "secret",
                "bucketname": "deliveries", "key_prefix": "incoming/product-c_delivery.zip",
            }, content_type="application/json", HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Delivery.objects.exists())
        self.assertFalse(S3Info.objects.exists())

    @override_settings(S3_ALLOWED_ENDPOINTS=("https://objects.example.com",))
    def test_s3_registration_without_assignments_avoids_remote_lookup(self):
        self.user.product_grants.all().delete()
        with patch("qc_tool.frontend.dashboard.views.api_access.deliveries.inspect_s3_delivery") as inspect:
            response = self.client.post(reverse("api_register_delivery_s3"), {
                "host": "https://objects.example.com", "access_key": "key", "secret_key": "secret",
                "bucketname": "deliveries", "key_prefix": "incoming/product-a_delivery.zip",
            }, content_type="application/json", HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(response.status_code, 403)
        inspect.assert_not_called()

    def test_browser_and_api_choices_include_only_assigned_products(self):
        with patch("qc_tool.frontend.dashboard.views.products.data.get_product_descriptions", return_value=self.descriptions):
            browser = self.client.get(reverse("product_list_json"))
        with patch("qc_tool.frontend.dashboard.views.api_access.products.get_product_descriptions", return_value=self.descriptions):
            api = self.client.get(reverse("api_product_list"), HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual({item["name"] for item in browser.json()["product_list"]}, {"product-a", "product-b"})
        self.assertEqual({item["product_ident"] for item in api.json()["products"]}, {"product-a", "product-b"})

    def test_job_setup_filters_choices_and_rejects_unassigned_owned_delivery(self):
        delivery = Delivery.objects.create(user=self.user, filename="unknown.zip", size_bytes=4)
        with patch("qc_tool.frontend.dashboard.views.jobs.setup.get_product_descriptions", return_value=self.descriptions):
            response = self.client.get(reverse("setup_job"), {"deliveries": str(delivery.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["product_ident"] for item in response.context["product_list"]}, {"product-a", "product-b"})
        delivery.product_ident = "product-c"
        delivery.save(update_fields=("product_ident",))
        self.assertEqual(self.client.get(reverse("setup_job"), {"deliveries": str(delivery.pk)}).status_code, 403)

    def test_unassigned_product_metadata_is_unavailable(self):
        for route in ("product_definition_json", "job_info_json"):
            self.assertEqual(self.client.get(reverse(route, args=("product-c",))).status_code, 404)
        api = self.client.get(reverse("api_product_info", args=("product-c",)), HTTP_AUTHORIZATION=self.authorization)
        self.assertEqual(api.status_code, 404)

    def link_definition(self, recipe, parent_ident, *, digest, current=False):
        definition, _ = QcDefinition.objects.get_or_create(
            product_ident=recipe, digest=digest,
            defaults={"description": recipe, "document": {"description": recipe, "steps": []}, "source_path": "test:recipe"},
        )
        parent, _ = Product.objects.get_or_create(ident=parent_ident, defaults={"name": parent_ident})
        release = ProductRelease.objects.create(
            product=parent, release_key=f"{parent_ident}-{recipe}-{digest[:1]}",
            revision=1, description=recipe, catalog_digest=digest, is_current=current,
        )
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition)
        return definition

    def test_parent_assignment_can_download_its_current_executable_recipe(self):
        self.link_definition("current-recipe", "product-a", digest="a" * 64, current=True)
        definition_file = self.media_root / "current-recipe.json"
        definition_file.write_text('{"description": "Current recipe", "steps": []}')
        with patch("qc_tool.frontend.dashboard.views.products.data.locate_product_definition", return_value=definition_file):
            response = self.client.get(reverse("product_definition_json", args=("current-recipe",)))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Current recipe", b"".join(response.streaming_content))

    def test_historical_definition_authorization_uses_exact_recorded_parent_links(self):
        historical = self.link_definition("shared-recipe", "product-a", digest="a" * 64)
        other_revision = self.link_definition("shared-recipe", "product-c", digest="b" * 64)
        # The current catalog associates the same recipe with our assigned
        # parent, but that must not expose the other parent's stored revision.
        self.link_definition("shared-recipe", "product-a", digest="c" * 64, current=True)
        url = reverse("product_definition_json", args=("shared-recipe",))
        self.assertEqual(self.client.get(url, {"digest": historical.digest}).status_code, 200)
        self.assertEqual(self.client.get(url, {"digest": other_revision.digest}).status_code, 404)
        self.user.product_grants.filter(product_ident="product-a").delete()
        self.assertEqual(self.client.get(url, {"digest": historical.digest}).status_code, 404)

    def test_shared_exact_definition_can_be_read_through_any_assigned_recorded_parent(self):
        definition = self.link_definition("shared-recipe", "product-c", digest="a" * 64)
        self.link_definition("shared-recipe", "product-a", digest=definition.digest)
        response = self.client.get(reverse("product_definition_json", args=("shared-recipe",)), {"digest": definition.digest})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), definition.document)
