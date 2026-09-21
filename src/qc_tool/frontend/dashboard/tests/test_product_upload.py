"""Product uploads preserve reviewed scope and publish runnable specifications."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

import qc_tool.common as common
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.role_permissions import capability_content_type
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductUnit, ProductRelease,
    ProductReleaseDefinition, QcDefinition,
)
from qc_tool.frontend.dashboard.services.product_units import create_delivery_job
from qc_tool.frontend.dashboard.services.catalog import list_current_product_coverage
from qc_tool.frontend.dashboard.services.catalog.definition_import import synchronize_definition_directories
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import MAX_DEFINITION_BYTES
from qc_tool.frontend.dashboard.services.catalog.specification_upload import (
    add_product_specification, read_specification_upload, remove_product_specification,
)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ProductSpecificationUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = get_user_model().objects.create_user(username="specification-admin")
        cls.administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        cls.viewer = get_user_model().objects.create_user(username="specification-viewer")
        cls.manager = get_user_model().objects.create_user(username="specification-manager")
        cls.manager.user_permissions.add(Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        ))
        cls.superuser = get_user_model().objects.create_superuser(
            username="specification-superuser", email="admin@example.test", password="test-only",
        )

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        configuration = patch.dict(common.CONFIG, product_dirs=[self.sources], work_dir=self.work)
        configuration.start()
        self.addCleanup(configuration.stop)
        self.url = reverse("product_upload")
        self.client.force_login(self.administrator)

    def document(self, *, codes=None):
        return {
            "description": "Uploaded example product",
            "steps": [{
                "check_ident": "qc_tool.vector.naming",
                "required": True,
                "parameters": {
                    "reference_year": "2026",
                    "aoi_codes": codes if codes is not None else ["CZ", "cz", "SK"],
                },
            }],
        }

    def payload(self, **kwargs):
        return json.dumps(self.document(**kwargs), indent=2).encode("utf-8") + b"\n"

    def file(self, name="new_product.json", payload=None):
        return SimpleUploadedFile(name, payload if payload is not None else self.payload(), content_type="application/json")

    def post(self, name="new_product.json", payload=None):
        return self.client.post(self.url, {"definition_file": self.file(name, payload)})

    def remove_url(self, ident="new_product"):
        return reverse("product_remove", args=(ident,))

    def version_path(self, payload=None, ident="new_product"):
        digest = hashlib.sha256(self.payload() if payload is None else payload).hexdigest()
        return self.work / "product_definitions" / ".versions" / ident / (digest + ".json")

    def create_delivery(self):
        return Delivery.objects.create(
            user=self.administrator, filename="example.zip", size_bytes=12,
        )

    def start_job(self, delivery):
        return create_delivery_job(
            delivery, product_ident="new_product", product_description="Uploaded example product",
            skip_steps=None, requested_by=self.administrator, request_source="browser",
        )

    def assert_no_product_created(self):
        self.assertFalse(Product.objects.exists())
        self.assertFalse(ProductRelease.objects.exists())
        self.assertFalse(QcDefinition.objects.exists())
        self.assertFalse(list((self.work / "product_definitions").rglob("*.json")))

    def audit_entries(self, action=ADDITION):
        return LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(Product), action_flag=action,
        )

    def test_catalog_starts_empty_and_only_uploaded_specifications_become_selectable(self):
        (self.sources / "bundled.json").write_text(json.dumps(self.document()))
        self.assertIn("bundled", common.get_product_descriptions())
        self.assertEqual(
            self.client.get(reverse("product_list_json")).json(),
            {"product_list": []},
        )

        response = self.post()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.get(reverse("product_list_json")).json()["product_list"],
            [{"name": "new_product", "description": "Uploaded example product"}],
        )
        self.assertEqual(list(Product.objects.values_list("ident", flat=True)), ["new_product"])
        self.assertFalse(self.client.get(reverse("products")).context["product_catalog"])
        draft = self.client.get(reverse("products"), {"product_view": "draft"})
        self.assertEqual(draft.context["product_view"], "draft")
        self.assertEqual([row["ident"] for row in draft.context["product_catalog"]], ["new_product"])
        self.assertEqual(
            self.client.get(reverse("product_definition_json", args=("bundled",))).status_code,
            404,
        )

    def test_administrator_page_uses_shared_workspace_and_native_upload_form(self):
        response = self.client.get(self.url)

        self.assertEqual(self.url, "/products/upload/")
        self.assertEqual(resolve(self.url).url_name, "product_upload")
        self.assertTemplateUsed(response, "dashboard/products/upload.html")
        self.assertTemplateUsed(response, "dashboard/layouts/upload_page.html")
        self.assertTemplateUsed(response, "dashboard/shared/uploads/picker.html")
        self.assertContains(response, 'class="qc-breadcrumb"')
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'name="definition_file"')
        self.assertContains(response, 'data-upload-list')
        self.assertContains(response, 'data-upload-announcement')
        self.assertContains(response, "Add specification")
        self.assertContains(response, "my_product.json")
        self.assertContains(response, "1 MiB")
        self.assert_no_product_created()

    def test_anonymous_and_default_users_cannot_upload(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        self.assert_no_product_created()

    def test_json_upload_response_reports_added_and_identical_retry_separately(self):
        added = self.client.post(
            self.url, {"definition_file": self.file()}, HTTP_ACCEPT="application/json",
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json(), {
            "status": "ok", "created": True, "product_ident": "new_product",
            "url": reverse("product_detail", args=("new_product",)),
            "message": "Added to Draft. Review and approve its delivery plan to activate it.",
        })
        repeated = self.client.post(
            self.url, {"definition_file": self.file()}, HTTP_ACCEPT="application/json",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["status"], "ok")
        self.assertFalse(repeated.json()["created"])
        self.assertIn("Already added", repeated.json()["message"])
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_identical_upload_with_queued_or_running_jobs_keeps_the_existing_product(self):
        self.assertEqual(self.post().status_code, 302)
        product = Product.objects.get()
        release = ProductRelease.objects.get()
        definition = QcDefinition.objects.get()
        job = self.start_job(self.create_delivery())

        for state in (common.JOB_WAITING, common.JOB_RUNNING):
            with self.subTest(state=state):
                job.job_status = state
                job.save(update_fields=("job_status",))
                response = self.client.post(
                    self.url, {"definition_file": self.file("NEW_PRODUCT.JSON")},
                    HTTP_ACCEPT="application/json",
                )

                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["created"])
                self.assertIn("Already added", response.json()["message"])
                self.assertEqual(list(Product.objects.values_list("pk", flat=True)), [product.pk])
                self.assertEqual(list(ProductRelease.objects.values_list("pk", flat=True)), [release.pk])
                self.assertEqual(list(QcDefinition.objects.values_list("pk", flat=True)), [definition.pk])
                self.assertEqual(self.audit_entries().count(), 1)
                self.assertFalse(self.audit_entries(CHANGE).exists())
                self.assertEqual(self.version_path().read_bytes(), self.payload())
                job.refresh_from_db()
                self.assertEqual(job.job_status, state)
                self.assertEqual(job.product_release_id, release.pk)
                self.assertEqual(job.qc_definition_id, definition.pk)

    def test_browser_identical_upload_explains_that_no_duplicate_was_created(self):
        self.assertEqual(self.post().status_code, 302)

        response = self.client.post(
            self.url, {"definition_file": self.file()}, follow=True,
        )

        self.assertContains(response, "already has this specification")
        self.assertContains(response, "No new product or specification version was created.")
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_json_upload_validation_is_per_file_and_failure_keeps_other_successes(self):
        accepted = self.client.post(
            self.url, {"definition_file": self.file()}, HTTP_ACCEPT="application/json",
        )
        rejected = self.client.post(
            self.url, {"definition_file": self.file("invalid_product.json", b"invalid json")},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json()["status"], "error")
        self.assertTrue(rejected.json()["message"])
        self.assertEqual(list(Product.objects.values_list("ident", flat=True)), ["new_product"])

    def test_json_upload_rejects_multiple_files_in_one_transaction(self):
        response = self.client.post(
            self.url, {"definition_file": [self.file("one.json"), self.file("two.json")]},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.assertIn("one JSON specification", response.json()["message"])
        self.assert_no_product_created()

    def test_json_upload_requires_admin_and_csrf(self):
        for user in (self.viewer, self.manager):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.post(
                    self.url, {"definition_file": self.file()}, HTTP_ACCEPT="application/json",
                )
                self.assertEqual(response.status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        response = client.post(
            self.url, {"definition_file": self.file()}, HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assert_no_product_created()

    def test_configuration_permission_without_admin_role_does_not_allow_upload(self):
        self.assertFalse(self.manager.groups.filter(name=Role.ADMIN.value).exists())
        self.client.force_login(self.manager)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        with self.assertRaises(PermissionDenied):
            add_product_specification(read_specification_upload(self.file()), actor=self.manager)
        with self.assertRaises(PermissionDenied):
            remove_product_specification("new_product", actor=self.manager)
        self.assert_no_product_created()

    def test_superuser_can_upload(self):
        self.client.force_login(self.superuser)

        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(self.audit_entries().get().user_id, self.superuser.pk)

    def test_upload_requires_csrf_and_disallows_unsupported_methods(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.post(self.url, {"definition_file": self.file()}).status_code, 403)
        self.assert_no_product_created()
        self.assertEqual(client.get(self.url).status_code, 200)
        response = client.post(
            self.url, {"definition_file": self.file()},
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.delete(self.url).status_code, 405)

    def test_upload_stores_queryable_snapshot_draft_product_units_and_exact_runtime_bytes(self):
        payload = self.payload()
        response = self.post(name="NEW_Product.JSON", payload=payload)

        self.assertRedirects(response, reverse("product_detail", args=("new_product",)))
        definition = QcDefinition.objects.get(document__steps__0__parameters__reference_year="2026")
        self.assertEqual(definition.product_ident, "new_product")
        self.assertEqual(definition.document, json.loads(payload))
        self.assertEqual(definition.digest, hashlib.sha256(payload).hexdigest())
        self.assertEqual(definition.source_path, "upload:new_product.json")
        release = ProductRelease.objects.get()
        self.assertEqual(release.source_kind, ProductRelease.SourceKind.UPLOAD)
        self.assertEqual(release.coverage_state, ProductRelease.CoverageState.DRAFT)
        self.assertTrue(release.is_current)
        self.assertIsNone(release.approved_at)
        self.assertEqual(list(ProductUnit.objects.values_list("product_unit_code", flat=True)), ["cz", "sk"])
        report = list_current_product_coverage()[0]
        self.assertEqual(report["declared_expected"], 2)
        self.assertIsNone(report["expected"])
        self.assertIsNone(report["completion_percentage"])
        target = self.version_path(payload)
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(common.current_product_specification_state("new_product"), {
            "active": True, "digest": definition.digest,
        })
        self.assertEqual(common.locate_product_definition("new_product"), target)
        self.assertEqual(common.load_product_definition("new_product")["steps"], self.document()["steps"])
        self.assertEqual(common.get_product_descriptions()["new_product"], self.document()["description"])
        self.assertEqual(list(self.sources.iterdir()), [])
        self.assertFalse(list((self.work / "product_definitions").glob(".specification-*.tmp")))
        self.assertIn(definition.digest, self.audit_entries().get().change_message)

    def test_wildcard_scope_remains_unknown_and_numeric_required_flags_are_supported(self):
        document = self.document(codes=["*"])
        document["steps"][0]["required"] = 1
        document["steps"].append({"check_ident": "qc_tool.vector.unzip", "required": 0})

        self.assertEqual(self.post(payload=json.dumps(document).encode()).status_code, 302)
        self.assertEqual(ProductRelease.objects.get().coverage_state, "unknown")
        self.assertFalse(ProductUnit.objects.exists())

    def test_identical_retry_is_idempotent_and_changed_content_creates_dated_revision(self):
        payload = self.payload()
        self.assertEqual(self.post(payload=payload).status_code, 302)
        self.assertEqual(self.post(payload=payload).status_code, 302)
        original = ProductRelease.objects.get()
        first_definition = QcDefinition.objects.get()
        revised_payload = self.payload(codes=["AT"])
        self.assertEqual(self.post(payload=revised_payload).status_code, 302)

        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(QcDefinition.objects.count(), 2)
        self.assertEqual(self.audit_entries().count(), 1)
        self.assertEqual(self.audit_entries(CHANGE).count(), 1)
        current = ProductRelease.objects.get(is_current=True)
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.release_key, original.release_key)
        self.assertEqual(current.supersedes_id, original.pk)
        original.refresh_from_db()
        self.assertFalse(original.is_current)
        self.assertEqual(self.version_path(payload).read_bytes(), payload)
        self.assertEqual(common.locate_product_definition("new_product"), self.version_path(revised_payload))
        self.assertEqual(self.version_path(revised_payload).read_bytes(), revised_payload)
        detail = self.client.get(reverse("product_detail", args=("new_product",)))
        versions = detail.context["specification_versions"]
        self.assertEqual(len(versions), 2)
        self.assertTrue(versions[0]["is_current"])
        self.assertGreaterEqual(versions[0]["imported_at"], first_definition.imported_at)
        self.assertEqual(versions[1]["digest"], first_definition.digest)
        self.assertFalse(versions[1]["is_current"])
        historical = self.client.get(
            reverse("product_definition_json", args=("new_product",)), {"digest": first_definition.digest},
        )
        self.assertEqual(historical.status_code, 200)
        self.assertEqual(historical.json(), json.loads(payload))

    def test_upload_revises_imported_product_without_changing_source_file(self):
        source = self.sources / "source_product.json"
        source.write_bytes(self.payload())
        synchronize_definition_directories([self.sources])
        original = ProductRelease.objects.get()

        self.assertEqual(self.post("SOURCE_PRODUCT.json", self.payload(codes=["AT"])).status_code, 302)

        current = ProductRelease.objects.get(is_current=True)
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.supersedes_id, original.pk)
        self.assertEqual(current.source_kind, ProductRelease.SourceKind.UPLOAD)
        self.assertEqual(source.read_bytes(), self.payload())
        self.assertEqual(common.locate_product_definition("source_product"), self.version_path(
            self.payload(codes=["AT"]), ident="source_product",
        ))

    def test_grouped_product_requires_reviewed_catalog_workflow(self):
        managed = Product.objects.create(ident="managed_product", name="Managed product")
        ProductRelease.objects.create(
            product=managed, release_key="managed-release", revision=1,
            description="Managed product", catalog_digest="a" * 64, is_current=True,
            source_kind=ProductRelease.SourceKind.MANIFEST,
        )
        response = self.post(name="managed_product.json")
        self.assertContains(response, "grouped release")
        self.assertTrue(response.context["form"].errors["definition_file"])
        self.assertFalse(QcDefinition.objects.exists())
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(ProductRelease.objects.count(), 1)
        self.assertFalse(list((self.work / "product_definitions").rglob("*.json")))

    def test_multiple_release_streams_cannot_be_overwritten_or_removed(self):
        self.assertEqual(self.post().status_code, 302)
        parallel = ProductRelease.objects.create(
            product=Product.objects.get(), release_key="parallel-release", revision=1,
            description="Parallel stream", catalog_digest="b" * 64, is_current=True,
            source_kind=ProductRelease.SourceKind.MANIFEST,
        )
        ProductReleaseDefinition.objects.create(
            product_release=parallel, qc_definition=QcDefinition.objects.get(), is_primary=True,
        )

        self.assertContains(self.post(payload=self.payload(codes=["AT"])), "grouped release")
        self.assertContains(self.client.post(self.remove_url()), "grouped release")
        self.assertTrue(Product.objects.get().is_active)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(QcDefinition.objects.count(), 1)

    def test_missing_multiple_empty_oversized_and_reserved_files_are_rejected(self):
        cases = [
            {},
            {"definition_file": [self.file("one.json"), self.file("two.json")]},
            {"definition_file": self.file(payload=b"")},
            {"definition_file": self.file(payload=b" " * (MAX_DEFINITION_BYTES + 1))},
            {"definition_file": self.file("specification.txt")},
            {"definition_file": self.file("list.json")},
            {"definition_file": self.file("upload.json")},
            {"definition_file": self.file("submissions.json")},
            {"definition_file": self.file("Submissions.json")},
            {"definition_file": self.file("unsafe name.json")},
        ]
        for index, files in enumerate(cases):
            with self.subTest(index=index):
                response = self.client.post(self.url, files)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["definition_file"])
                self.assert_no_product_created()

    def test_malformed_json_and_unsafe_or_unavailable_checks_are_rejected(self):
        invalid_documents = [
            b"not json",
            b"\xff",
            b'{"description":"first","description":"second","steps":[]}',
            b'{"description":"example","steps":[],"value":NaN}',
            b'{"description":"example","steps":[],"value":1e999}',
            json.dumps({**self.document(), "note": "\u0000"}).encode(),
            json.dumps({**self.document(), "note": "\ud800"}).encode(),
        ]
        for step in (
            {"check_ident": "os.system", "required": True},
            {"check_ident": "qc_tool.vector.does_not_exist", "required": True},
            {"check_ident": "qc_tool.vector.naming"},
            {"check_ident": "qc_tool.vector.naming", "required": "true"},
            {"check_ident": "qc_tool.vector.naming", "required": 2},
            {"check_ident": "qc_tool.vector.naming", "required": True, "parameters": []},
        ):
            invalid_documents.append(json.dumps({"description": "Invalid product", "steps": [step]}).encode())
        invalid_documents.append(json.dumps({"description": "No checks", "steps": []}).encode())
        invalid_documents.append(self.payload(codes=[" "]))

        for payload in invalid_documents:
            with self.subTest(payload=payload[:100]):
                response = self.post(payload=payload)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors["definition_file"])
                self.assert_no_product_created()

    def test_failed_file_publication_can_be_completed_by_identical_retry(self):
        with patch(
            "qc_tool.frontend.dashboard.services.catalog.specification_upload.publish_specification",
            side_effect=OSError("storage unavailable"),
        ), self.assertLogs("qc_tool.frontend.dashboard.services.catalog.specification_upload", level="ERROR"):
            response = self.post()

        self.assertContains(response, "upload the same file again")
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(QcDefinition.objects.count(), 1)
        target = self.version_path()
        self.assertFalse(target.exists())
        self.assertFalse(list((self.work / "product_definitions").glob(".specification-*.tmp")))
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(target.read_bytes(), self.payload())
        self.assertEqual(ProductRelease.objects.count(), 1)
        self.assertEqual(QcDefinition.objects.count(), 1)
        self.assertEqual(self.audit_entries().count(), 1)

    def test_directory_import_does_not_take_ownership_of_uploaded_release(self):
        self.assertEqual(self.post().status_code, 302)
        original = ProductRelease.objects.get()
        imported = self.root / "imported"
        imported.mkdir()
        (imported / "new_product.json").write_bytes(self.payload(codes=["AT"]))

        result = synchronize_definition_directories([imported])

        self.assertEqual(result.managed_definitions, 1)
        self.assertEqual(ProductRelease.objects.count(), 1)
        current = ProductRelease.objects.get(is_current=True)
        self.assertEqual(current.pk, original.pk)
        self.assertEqual(current.source_kind, ProductRelease.SourceKind.UPLOAD)
        self.assertEqual(list(current.product_units.values_list("product_unit_code", flat=True)), ["cz", "sk"])
        self.assertEqual(self.version_path().read_bytes(), self.payload())

    def test_removal_requires_administrator_role_csrf_and_explicit_post(self):
        self.assertEqual(self.post().status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.remove_url()).status_code, 302)
        for user in (self.viewer, self.manager):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.remove_url()).status_code, 403)
                self.assertEqual(self.client.post(self.remove_url()).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        confirmation = client.get(self.remove_url())
        self.assertTemplateUsed(confirmation, "dashboard/products/remove.html")
        self.assertContains(confirmation, 'name="csrfmiddlewaretoken"')
        self.assertTrue(Product.objects.get().is_active)
        self.assertEqual(client.post(self.remove_url()).status_code, 403)
        self.assertTrue(Product.objects.get().is_active)
        self.assertEqual(client.delete(
            self.remove_url(), HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        ).status_code, 405)
        response = client.post(
            self.remove_url(), HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        )
        self.assertRedirects(response, reverse("products") + "?product_view=stopped")
        self.assertFalse(Product.objects.get().is_active)
        self.assertEqual(self.audit_entries(DELETION).get().user_id, self.administrator.pk)

    def test_admin_controls_are_hidden_from_non_administrators(self):
        self.assertEqual(self.post().status_code, 302)
        detail_url = reverse("product_detail", args=("new_product",))
        for user in (self.viewer, self.manager):
            with self.subTest(user=user.username):
                UserProductGrant.objects.create(user=user, product_ident="new_product")
                self.client.force_login(user)
                self.assertNotContains(self.client.get(reverse("products")), self.url)
                detail = self.client.get(detail_url)
                self.assertNotContains(detail, self.url)
                self.assertNotContains(detail, self.remove_url())
        self.client.force_login(self.administrator)
        self.assertContains(self.client.get(reverse("products")), self.url)
        self.assertContains(self.client.get(detail_url), self.remove_url())

    def test_archive_hides_runtime_and_catalog_then_upload_restores_another_revision(self):
        # A packaged copy with the same identifier must not reappear on archive.
        (self.sources / "new_product.json").write_bytes(self.payload())
        self.assertEqual(self.post().status_code, 302)
        definition = QcDefinition.objects.get()
        first_release = ProductRelease.objects.get()

        self.assertEqual(self.client.post(self.remove_url()).status_code, 302)

        self.assertFalse(Product.objects.get().is_active)
        self.assertEqual(common.current_product_specification_state("new_product"), {"active": False})
        with self.assertRaises(common.QCException):
            common.locate_product_definition("new_product")
        self.assertNotIn("new_product", common.get_product_descriptions())
        self.assertEqual(list_current_product_coverage(), ())
        catalog = self.client.get(reverse("products"))
        self.assertFalse(catalog.context["product_catalog"])
        archive = self.client.get(reverse("products"), {"product_view": "stopped"})
        self.assertEqual([row["ident"] for row in archive.context["product_catalog"]], ["new_product"])
        detail = self.client.get(reverse("product_detail", args=("new_product",)))
        self.assertFalse(detail.context["product_is_active"])
        self.assertFalse(detail.context["specification_versions"][0]["is_current"])
        self.assertEqual(self.version_path().read_bytes(), self.payload())
        self.assertEqual(self.client.get(
            reverse("product_definition_json", args=("new_product",)),
            {"digest": definition.digest},
        ).json(), self.document())
        self.assertEqual(self.client.get(reverse("product_definition_json", args=("new_product",))).status_code, 404)

        result = synchronize_definition_directories([self.sources])
        self.assertEqual(result.managed_definitions, 1)
        self.assertFalse(Product.objects.get().is_active)
        self.assertEqual(ProductRelease.objects.count(), 1)
        self.assertEqual(self.client.post(self.remove_url()).status_code, 302)
        self.assertEqual(self.audit_entries(DELETION).count(), 1)

        self.assertEqual(self.post().status_code, 302)
        self.assertTrue(Product.objects.get().is_active)
        restored = ProductRelease.objects.get(is_current=True)
        self.assertEqual(restored.revision, 2)
        self.assertEqual(restored.supersedes_id, first_release.pk)
        self.assertEqual(QcDefinition.objects.count(), 1)
        definition.refresh_from_db()
        self.assertEqual(definition.digest, hashlib.sha256(self.payload()).hexdigest())
        self.assertEqual(common.locate_product_definition("new_product"), self.version_path())
        self.assertEqual(len(list_current_product_coverage()), 1)

    def test_unassigned_user_cannot_list_stopped_products(self):
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(self.client.post(self.remove_url()).status_code, 302)
        self.client.force_login(self.manager)

        response = self.client.get(reverse("products"), {"product_view": "stopped"})

        self.assertRedirects(response, reverse("products"))

    def test_waiting_and_running_jobs_prevent_revision_changes_or_removal(self):
        self.assertEqual(self.post().status_code, 302)
        job = self.start_job(self.create_delivery())
        self.assertEqual(job.qc_definition_id, QcDefinition.objects.get().pk)
        self.assertEqual(job.product_release_id, ProductRelease.objects.get().pk)

        for state in (common.JOB_WAITING, common.JOB_RUNNING):
            with self.subTest(state=state):
                job.job_status = state
                job.save(update_fields=("job_status",))
                self.assertContains(self.post(payload=self.payload(codes=["AT"])), "queued or running")
                self.assertContains(self.client.post(self.remove_url()), "queued or running")
                self.assertTrue(Product.objects.get().is_active)
                self.assertEqual(ProductRelease.objects.count(), 1)
                self.assertEqual(QcDefinition.objects.count(), 1)
                self.assertEqual(common.locate_product_definition("new_product"), self.version_path())

    def test_archive_and_revision_preserve_published_deliveries_and_their_exact_definition(self):
        self.assertEqual(self.post().status_code, 302)
        delivery = self.create_delivery()
        job = self.start_job(delivery)
        job.job_status = common.JOB_OK
        job.save(update_fields=("job_status",))
        original_release = job.product_release
        original_definition = job.qc_definition
        artifact = self.root / "published-delivery.zip"
        artifact.write_bytes(b"retained publication fixture")
        submission = DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=original_release,
            product_unit=original_release.product_units.get(product_unit_code="cz"),
            product_unit_code="cz", verified_product_unit_code="cz", submitted_by=self.administrator,
            submitted_by_username=self.administrator.username, request_channel="browser",
            publication_state="published", published_at=timezone.now(),
            artifact_key=artifact.name, artifact_digest="a" * 64, input_digest="b" * 64,
        )
        before = DeliverySubmission.objects.filter(pk=submission.pk).values().get()

        self.assertEqual(self.post(payload=self.payload(codes=["AT"])).status_code, 302)
        self.assertEqual(self.client.post(self.remove_url()).status_code, 302)

        job.refresh_from_db()
        self.assertEqual(job.qc_definition_id, original_definition.pk)
        self.assertEqual(job.product_release_id, original_release.pk)
        self.assertEqual(job.job_status, common.JOB_OK)
        self.assertEqual(DeliverySubmission.objects.filter(pk=submission.pk).values().get(), before)
        self.assertTrue(Delivery.objects.filter(pk=delivery.pk).exists())
        self.assertEqual(artifact.read_bytes(), b"retained publication fixture")
        self.assertEqual(self.version_path().read_bytes(), self.payload())
        self.assertEqual(QcDefinition.objects.get(pk=original_definition.pk).document, self.document())

    def test_pending_activation_and_archived_specifications_cannot_start_jobs(self):
        delivery = self.create_delivery()
        with patch(
            "qc_tool.frontend.dashboard.services.catalog.specification_upload.publish_specification",
            side_effect=OSError("storage unavailable"),
        ), self.assertLogs("qc_tool.frontend.dashboard.services.catalog.specification_upload", level="ERROR"):
            self.assertEqual(self.post().status_code, 200)

        with self.assertRaisesRegex(ValueError, "awaiting activation"):
            self.start_job(delivery)
        self.assertFalse(Job.objects.exists())
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(self.client.post(self.remove_url()).status_code, 302)
        with self.assertRaisesRegex(ValueError, "has been stopped"):
            self.start_job(delivery)
        self.assertFalse(Job.objects.exists())

    def test_failed_removal_disables_new_jobs_and_can_be_retried(self):
        self.assertEqual(self.post().status_code, 302)
        with patch(
            "qc_tool.frontend.dashboard.services.catalog.specification_upload.publish_specification_state",
            side_effect=OSError("storage unavailable"),
        ), self.assertLogs("qc_tool.frontend.dashboard.services.catalog.specification_upload", level="ERROR"):
            response = self.client.post(self.remove_url())

        self.assertContains(response, "Retry stopping")
        self.assertFalse(Product.objects.get().is_active)
        self.assertTrue(common.current_product_specification_state("new_product")["active"])
        pending = self.client.get(self.remove_url())
        self.assertTrue(pending.context["removal_pending"])
        self.assertContains(pending, 'name="csrfmiddlewaretoken"')
        self.assertContains(pending, "Retry stopping")
        with self.assertRaisesRegex(ValueError, "has been stopped"):
            self.start_job(self.create_delivery())
        self.assertEqual(self.client.post(self.remove_url()).status_code, 302)
        self.assertEqual(common.current_product_specification_state("new_product"), {"active": False})
        self.assertEqual(self.audit_entries(DELETION).count(), 1)

    def test_changed_revision_waits_for_runtime_activation_and_identical_retry_completes_it(self):
        self.assertEqual(self.post().status_code, 302)
        original = QcDefinition.objects.get()
        revised_payload = self.payload(codes=["AT"])
        with patch(
            "qc_tool.frontend.dashboard.services.catalog.specification_upload.publish_specification",
            side_effect=OSError("storage unavailable"),
        ), self.assertLogs("qc_tool.frontend.dashboard.services.catalog.specification_upload", level="ERROR"):
            self.assertEqual(self.post(payload=revised_payload).status_code, 200)

        self.assertEqual(common.current_product_specification_state("new_product")["digest"], original.digest)
        with self.assertRaisesRegex(ValueError, "awaiting activation"):
            self.start_job(self.create_delivery())
        self.assertFalse(Job.objects.exists())
        self.assertEqual(self.post(payload=revised_payload).status_code, 302)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(QcDefinition.objects.count(), 2)
        job = self.start_job(self.create_delivery())
        self.assertEqual(job.qc_definition.digest, hashlib.sha256(revised_payload).hexdigest())
        self.assertEqual(job.product_release.revision, 2)

    def test_first_identical_import_upload_claims_ownership_then_retries_are_idempotent(self):
        (self.sources / "new_product.json").write_bytes(self.payload())
        synchronize_definition_directories([self.sources])
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(ProductRelease.objects.get(is_current=True).source_kind, "upload")
        self.assertEqual(QcDefinition.objects.count(), 1)

    def test_job_revalidates_skip_steps_against_the_selected_revision(self):
        optional = self.document()
        optional["steps"][0]["required"] = False
        self.assertEqual(self.post(payload=json.dumps(optional).encode()).status_code, 302)
        common.validate_skip_steps([1], optional)
        self.assertEqual(self.post().status_code, 302)
        with self.assertRaisesRegex(ValueError, "Review the selected QC steps"):
            create_delivery_job(
                self.create_delivery(), product_ident="new_product",
                product_description="Stale description", skip_steps="1",
                requested_by=self.administrator,
            )
        self.assertFalse(Job.objects.exists())
