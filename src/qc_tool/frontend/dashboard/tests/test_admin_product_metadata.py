"""Product display edits preserve catalog evidence and maintenance fencing."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Product, ProductRelease, ProductReleaseDefinition, ProductUnit, QcDefinition
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.catalog.product_metadata import metadata_version, update_product_metadata


@override_settings(MAINTENANCE_MODE=False)
class ProductMetadataAdminTests(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=self.directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.directory / "transfers",
        ))
        User = get_user_model()
        self.administrator = User.objects.create_user(username="metadata-administrator")
        self.administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.manager = User.objects.create_user(username="metadata-manager")
        self.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.ordinary = User.objects.create_user(username="metadata-reader")
        self.product = Product.objects.create(
            ident="metadata-product", name="Original name", description="Original description",
            readiness_revision=7, ready_at=timezone.now(), ready_by=self.administrator,
            ready_by_username=self.administrator.username, ready_scope_digest="d" * 64,
        )
        UserProductGrant.objects.create(user=self.manager, product_ident=self.product.ident)
        self.specification = self.directory / "metadata-product.json"
        self.specification.write_bytes(b'{ "description": "Original specification", "steps": [] }\n')
        self.definition = QcDefinition.objects.create(
            product_ident=self.product.ident, digest="a" * 64, description="Original specification",
            document={"description": "Original specification", "steps": []}, source_path=str(self.specification),
        )
        self.release = ProductRelease.objects.create(
            product=self.product, release_key="metadata-release", revision=1,
            description="Original release", catalog_digest="b" * 64, is_current=True,
            coverage_state=ProductRelease.CoverageState.AUTHORITATIVE,
            approved_at=timezone.now(), approved_by=self.administrator,
        )
        ProductReleaseDefinition.objects.create(product_release=self.release, qc_definition=self.definition, is_primary=True)
        ProductUnit.objects.create(product_release=self.release, product_unit_code="unit-1", provenance="test")
        self.url = reverse("admin:dashboard_product_change", args=[self.product.pk])
        self.client.force_login(self.administrator)

    def payload(self, **updates):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        form = response.context["adminform"].form
        return {"name": "Updated name", "description": "Updated description",
                "metadata_version": form["metadata_version"].value(), "_save": "Save", **updates}

    def product_values(self):
        return Product.objects.values().get(pk=self.product.pk)

    def evidence(self):
        return {
            "definitions": list(QcDefinition.objects.values()),
            "releases": list(ProductRelease.objects.values()),
            "links": list(ProductReleaseDefinition.objects.values()),
            "units": list(ProductUnit.objects.values()),
            "specification": self.specification.read_bytes(),
        }

    def test_qc_administrator_can_edit_only_display_fields_and_gets_standard_audit(self):
        before, evidence = self.product_values(), self.evidence()
        response = self.client.post(self.url, self.payload())
        self.assertEqual(response.status_code, 302)
        after = self.product_values()
        self.assertEqual((after["name"], after["description"]), ("Updated name", "Updated description"))
        self.assertGreater(after["updated_at"], before["updated_at"])
        self.assertEqual({key: value for key, value in after.items() if key not in {"name", "description", "updated_at"}},
                         {key: value for key, value in before.items() if key not in {"name", "description", "updated_at"}})
        self.assertEqual(self.evidence(), evidence)
        log = LogEntry.objects.get(object_id=str(self.product.pk), action_flag=CHANGE)
        self.assertEqual(log.user_id, self.administrator.pk)
        self.assertIn("Name", log.change_message)
        self.assertIn("Description", log.change_message)

    def test_edit_form_keeps_ident_lifecycle_and_readiness_read_only(self):
        response = self.client.get(self.url)
        form = response.context["adminform"].form
        self.assertEqual(set(form.fields), {"name", "description", "metadata_version"})
        self.assertContains(response, 'type="hidden" name="metadata_version"')
        for field in ("ident", "is_active", "readiness_revision", "ready_at", "ready_scope_digest", "updated_at"):
            self.assertNotContains(response, f'name="{field}"')

    def test_editable_metadata_precedes_collapsed_protected_details(self):
        response = self.client.get(self.url)
        fieldsets = list(response.context["adminform"].fieldsets)
        self.assertEqual(fieldsets[0], ("Product metadata", {"fields": ("name", "description", "metadata_version")}))
        self.assertEqual(fieldsets[1][0], "Protected product details")
        self.assertEqual(fieldsets[1][1]["classes"], ("collapse",))
        self.assertIn("ident", fieldsets[1][1]["fields"])
        self.assertIn("readiness_revision", fieldsets[1][1]["fields"])
        self.assertNotIn("name", fieldsets[1][1]["fields"])
        self.assertContains(response, '<details><summary>', html=False)
        self.assertNotContains(response, '<details open>')

    def test_stale_metadata_page_is_a_form_error_and_keeps_newer_values(self):
        payload = self.payload()
        update_product_metadata(product_id=self.product.pk, name="Newer name", description="Newer description",
                                expected_version=payload["metadata_version"], actor=self.administrator)
        before = self.product_values()
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This product changed.")
        self.assertTrue(response.context["adminform"].form.non_field_errors())
        self.assertEqual(self.product_values(), before)
        self.assertFalse(LogEntry.objects.filter(object_id=str(self.product.pk)).exists())

    def test_readiness_change_without_timestamp_change_also_invalidates_review(self):
        payload = self.payload()
        original_timestamp = self.product.updated_at
        Product.objects.filter(pk=self.product.pk).update(readiness_revision=8)
        self.assertEqual(self.product_values()["updated_at"], original_timestamp)
        response = self.client.post(self.url, payload)
        self.assertContains(response, "This product changed.", status_code=200)
        self.assertEqual(self.product_values()["name"], "Original name")
        self.assertEqual(self.product_values()["readiness_revision"], 8)

    def test_protected_fields_in_forged_posts_are_rejected_without_changes(self):
        original = self.product_values()
        for field, value in (("ident", "renamed-product"), ("is_active", ""),
                             ("readiness_revision", "99"), ("ready_by_id", self.manager.pk),
                             ("ready_scope_digest", "f" * 64), ("updated_at", "2000-01-01T00:00:00")):
            with self.subTest(field=field):
                response = self.client.post(self.url, self.payload(**{field: value}))
                self.assertContains(response, "Only the product name and description", status_code=200)
                self.assertEqual(self.product_values(), original)
        self.assertFalse(LogEntry.objects.filter(object_id=str(self.product.pk)).exists())

    def test_missing_or_invalid_version_is_an_error_without_a_write(self):
        for version in (None, "not-a-version"):
            with self.subTest(version=version):
                payload = self.payload()
                if version is None:
                    del payload["metadata_version"]
                else:
                    payload["metadata_version"] = version
                response = self.client.post(self.url, payload)
                self.assertEqual(response.status_code, 200)
                self.assertIn("metadata_version", response.context["adminform"].form.errors)
                self.assertEqual(self.product_values()["name"], "Original name")

    def test_invalid_display_metadata_is_reported_in_the_form(self):
        response = self.client.post(self.url, self.payload(name=""))
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["adminform"].form.errors)
        self.assertEqual(self.product_values()["name"], "Original name")

    def test_product_manager_retains_scoped_read_only_access(self):
        payload = self.payload()
        self.client.force_login(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="name"')
        self.assertNotContains(response, 'name="description"')
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        self.assertEqual(self.product_values()["name"], "Original name")

    def test_ordinary_user_cannot_open_or_post_metadata_form(self):
        payload = self.payload()
        self.client.force_login(self.ordinary)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, payload).status_code, 302)
        self.assertEqual(self.product_values()["name"], "Original name")

    def test_product_add_and_delete_remain_unavailable(self):
        self.assertEqual(self.client.get(reverse("admin:dashboard_product_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:dashboard_product_delete", args=[self.product.pk])).status_code, 403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_maintenance_blocks_ordinary_admin_metadata_post(self):
        payload = self.payload()
        generation = maintenance.enable(self.administrator, expected_generation=0)["generation"]
        maintenance.advance(expected_generation=generation)
        before = self.product_values()
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.product_values(), before)
        self.assertFalse(LogEntry.objects.filter(object_id=str(self.product.pk)).exists())

    def test_service_validates_fields_and_rejects_nonadministrator(self):
        original = self.product_values()
        with self.assertRaises(ValidationError):
            update_product_metadata(product_id=self.product.pk, name="", description="invalid",
                                    expected_version=metadata_version(self.product), actor=self.administrator)
        with self.assertRaises(PermissionDenied):
            update_product_metadata(product_id=self.product.pk, name="Denied", description="Denied",
                                    expected_version=metadata_version(self.product), actor=self.manager)
        self.assertEqual(self.product_values(), original)
