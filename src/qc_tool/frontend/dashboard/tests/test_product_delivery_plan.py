"""Delivery plan activation is explicit, scoped and preserves provenance."""

import json

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.role_permissions import capability_content_type
from qc_tool.frontend.dashboard.forms.product_delivery_plan import ProductDeliveryPlanForm
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, ProductAOI, ProductRelease, ProductReleaseDefinition, QcDefinition,
)
from qc_tool.frontend.dashboard.services.catalog import list_current_product_coverage
from qc_tool.frontend.dashboard.services.catalog.contracts import CatalogSnapshot
from qc_tool.frontend.dashboard.services.catalog.delivery_plans import (
    approve_delivery_plan, current_product_manager_ids, manager_assignment_digest,
)
from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import parse_definition_snapshot
from qc_tool.frontend.dashboard.services.catalog.manifest.release_parser import parse_release_document
from qc_tool.frontend.dashboard.services.catalog.sync.service import synchronize_product_catalog


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ProductDeliveryPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="plan-admin")
        cls.admin.groups.add(Group.objects.get(name=Role.ADMIN.value))
        cls.manager = get_user_model().objects.create_user(username="plan-manager")
        cls.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        cls.other_manager = get_user_model().objects.create_user(username="other-plan-manager")
        cls.other_manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        cls.user = get_user_model().objects.create_user(username="plan-user")
        definition = parse_definition_snapshot("planned_product", json.dumps({
            "description": "Planned product",
            "steps": [{
                "check_ident": "qc_tool.vector.naming", "required": True,
                "parameters": {"aoi_codes": ["CZ", "SK", "AT"]},
            }],
        }).encode(), source_path="test:planned_product.json")
        snapshot = parse_release_document(
            {
                "release_key": "definition:planned_product", "revision": 1,
                "description": "Planned product", "definition_idents": ["planned_product"],
                "coverage": {"state": "draft", "source_definition": "planned_product"},
            },
            product_ident="planned_product", product_name="Planned product",
            product_description="Expected deliveries", definition_loader=lambda _ident: definition,
            source_kind="upload",
        )
        synchronize_product_catalog(CatalogSnapshot(releases=(snapshot,)))
        cls.release = ProductRelease.objects.get(is_current=True)

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("product_plan_edit", args=("planned_product", self.release.pk))

    def approve(self, *, release=None, codes=None, managers=(), actor=None, expected=None, manager_digest=None):
        release = release or self.release
        return approve_delivery_plan(
            "planned_product", release.pk,
            expected_release_id=release.pk if expected is None else expected,
            expected_manager_digest=manager_digest or manager_assignment_digest(current_product_manager_ids("planned_product")),
            aoi_codes=["CZ", "SK"] if codes is None else codes,
            actor=actor or self.admin, product_managers=managers,
        )

    def post_data(self, **overrides):
        return {
            "expected_release_id": self.release.pk,
            "expected_manager_digest": manager_assignment_digest(current_product_manager_ids("planned_product")),
            "aoi_codes": "CZ\nSK", "confirm_approval": "on",
            "product_managers": [str(self.manager.pk)], **overrides,
        }

    def test_page_prefills_the_declared_scope_and_existing_managers(self):
        UserProductGrant.objects.create(user=self.manager, product_ident="planned_product")
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/products/plan.html")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertEqual(response.context["form"].initial["aoi_codes"], "at\ncz\nsk")
        self.assertEqual(list(response.context["form"].initial["product_managers"]), [self.manager.pk])
        self.assertEqual(response.context["expected_aoi_count"], 3)
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_only_administrators_can_access_or_approve_plans(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.manager.user_permissions.add(Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        ))
        for actor in (self.user, self.manager):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 403)
                with self.assertRaises(PermissionDenied):
                    self.approve(actor=actor)
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_approval_requires_csrf_and_explicit_confirmation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url, self.post_data()).status_code, 403)
        client.get(self.url)
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.delete(self.url, HTTP_X_CSRFTOKEN=token).status_code, 405)
        response = client.post(self.url, self.post_data(confirm_approval=""), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["confirm_approval"])
        self.assertEqual(ProductRelease.objects.count(), 1)
        response = client.post(self.url, self.post_data(), HTTP_X_CSRFTOKEN=token)
        self.assertRedirects(response, reverse("product_detail", args=("planned_product",)))

    def test_approval_creates_authoritative_revision_and_records_the_administrator(self):
        approved = self.approve(codes=["CZ", "cz", "SK"], managers=(self.manager,))

        self.release.refresh_from_db()
        self.assertFalse(self.release.is_current)
        self.assertEqual(self.release.coverage_state, "draft")
        self.assertEqual(approved.coverage_state, "authoritative")
        self.assertTrue(approved.is_current)
        self.assertEqual(approved.revision, 2)
        self.assertEqual(approved.supersedes_id, self.release.pk)
        self.assertEqual(approved.approved_by_id, self.admin.pk)
        self.assertIsNotNone(approved.approved_at)
        self.assertEqual(list(approved.aois.values_list("aoi_code", flat=True)), ["cz", "sk"])
        self.assertEqual(set(approved.aois.values_list("provenance", flat=True)), {"administrator"})
        self.assertEqual(approved.definition_links.get().qc_definition_id, self.release.definition_links.get().qc_definition_id)
        self.assertEqual(QcDefinition.objects.count(), 1)
        self.assertEqual(LogEntry.objects.get().user_id, self.admin.pk)
        self.assertEqual(UserProductGrant.objects.get().created_by_id, self.admin.pk)

    def test_stale_and_cross_product_posts_cannot_replace_the_current_plan(self):
        approved = self.approve()
        for call in (
            lambda: self.approve(),
            lambda: self.approve(release=approved, expected=self.release.pk),
            lambda: approve_delivery_plan(
                "another_product", approved.pk, expected_release_id=approved.pk,
                expected_manager_digest=manager_assignment_digest(()),
                aoi_codes=["CZ"], actor=self.admin,
            ),
        ):
            with self.assertRaises(CatalogError):
                call()
        self.assertEqual(ProductRelease.objects.get(is_current=True).pk, approved.pk)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(self.client.get(reverse("product_plan_edit", args=("another_product", approved.pk))).status_code, 404)

    def test_unknown_scope_can_be_defined_explicitly(self):
        ProductAOI.objects.filter(product_release=self.release).delete()
        ProductRelease.objects.filter(pk=self.release.pk).update(coverage_state="unknown")
        approved = self.approve(codes=["AT"])

        self.assertEqual(approved.coverage_state, "authoritative")
        self.assertEqual(list(approved.aois.values_list("aoi_code", flat=True)), ["at"])

    def test_empty_invalid_or_unsupported_aoi_scopes_are_rejected(self):
        for codes in ([], ["*"], ["CZ", "*"], ["../escape"], ["a\\b"], ["bad\x00code"], ["x" * 256], ["DE"]):
            with self.subTest(codes=codes), self.assertRaises(CatalogError):
                self.approve(codes=codes)
        self.assertEqual(ProductRelease.objects.count(), 1)
        self.assertFalse(LogEntry.objects.exists())

    def test_wildcard_naming_allows_an_explicit_plan(self):
        self._replace_naming_steps([["*"]])
        approved = self.approve(codes=["DE"])
        self.assertEqual(list(approved.aois.values_list("aoi_code", flat=True)), ["de"])

    def test_wildcard_check_does_not_override_another_finite_naming_check(self):
        self._replace_naming_steps([["CZ", "SK"], ["*"]])
        with self.assertRaisesRegex(CatalogError, "outside the specification"):
            self.approve(codes=["DE"])
        self.assertEqual(ProductRelease.objects.count(), 1)

    def _replace_naming_steps(self, scopes):
        document = {
            "description": "Replacement scope fixture",
            "steps": [{
                "check_ident": "qc_tool.vector.naming", "required": True,
                "parameters": {"aoi_codes": scope},
            } for scope in scopes],
        }
        snapshot = parse_definition_snapshot(
            "planned_product", json.dumps(document).encode(), source_path="test:replacement.json",
        )
        definition = QcDefinition.objects.create(
            product_ident=snapshot.product_ident, description=snapshot.description,
            digest=snapshot.digest, document=snapshot.document, source_path=snapshot.source_path,
        )
        ProductReleaseDefinition.objects.filter(product_release=self.release).update(qc_definition=definition)

    def test_archived_products_cannot_activate_a_plan(self):
        product = self.release.product
        product.is_active = False
        product.save(update_fields=("is_active",))

        with self.assertRaisesRegex(CatalogError, "Restore this product"):
            self.approve()
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_missing_or_ambiguous_primary_specifications_are_rejected(self):
        ProductReleaseDefinition.objects.filter(product_release=self.release).update(is_primary=False)
        with self.assertRaisesRegex(CatalogError, "Upload a product specification"):
            self.approve()
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_repeated_current_plan_is_idempotent(self):
        approved = self.approve(managers=(self.manager,))
        repeated = self.approve(release=approved, codes=["SK", "cz", "CZ"], managers=(self.manager,))

        self.assertEqual(approved.pk, repeated.pk)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(LogEntry.objects.count(), 1)

    def test_manager_assignments_preserve_other_products_and_regular_user_grants(self):
        UserProductGrant.objects.create(user=self.other_manager, product_ident="planned_product")
        UserProductGrant.objects.create(user=self.other_manager, product_ident="another_product")
        UserProductGrant.objects.create(user=self.user, product_ident="planned_product")
        approved = self.approve(managers=(self.manager,))

        self.assertTrue(UserProductGrant.objects.filter(user=self.manager, product_ident="planned_product").exists())
        self.assertFalse(UserProductGrant.objects.filter(user=self.other_manager, product_ident="planned_product").exists())
        self.assertTrue(UserProductGrant.objects.filter(user=self.other_manager, product_ident="another_product").exists())
        self.assertTrue(UserProductGrant.objects.filter(user=self.user, product_ident="planned_product").exists())
        manager_digest = manager_assignment_digest(current_product_manager_ids("planned_product"))
        aoi_ids = list(approved.aois.values_list("pk", flat=True))
        revised = self.approve(release=approved, managers=(self.other_manager,))
        self.assertEqual(revised.pk, approved.pk)
        self.assertEqual(list(revised.aois.values_list("pk", flat=True)), aoi_ids)
        self.assertEqual(ProductRelease.objects.count(), 2)
        with self.assertRaisesRegex(CatalogError, "assignments have changed"):
            self.approve(release=approved, managers=(self.manager,), manager_digest=manager_digest)

    def test_invalid_or_inactive_managers_cannot_receive_assignments(self):
        self.other_manager.is_active = False
        self.other_manager.save(update_fields=("is_active",))
        for user in (self.user, self.other_manager):
            with self.subTest(user=user.username), self.assertRaisesRegex(CatalogError, "active users"):
                self.approve(managers=(user,))
        self.assertEqual(ProductRelease.objects.count(), 1)
        self.assertFalse(UserProductGrant.objects.exists())

    def test_assignment_only_changes_preserve_accepted_submission_progress(self):
        approved = self.approve(managers=(self.manager,))
        delivery = Delivery.objects.create(user=self.user, filename="accepted.zip", size_bytes=12)
        job = Job.objects.create(
            delivery=delivery, requested_by=self.user, product_ident="planned_product",
            product_release=approved, qc_definition=approved.definition_links.get().qc_definition,
        )
        submission = DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=approved,
            product_aoi=approved.aois.get(aoi_code="cz"),
            aoi_code="cz", aoi_code_submitted="cz", submitted_by=self.user,
            submitted_by_username=self.user.username, request_channel="browser",
            publication_state="published", review_state="accepted",
            published_at=timezone.now(), artifact_path="/retained/accepted",
            artifact_digest="a" * 64, input_digest="b" * 64,
        )
        before = list_current_product_coverage(release_ids=(approved.pk,))
        updated = self.approve(release=approved, managers=(self.other_manager,))

        self.assertEqual(updated.pk, approved.pk)
        self.assertEqual(list_current_product_coverage(release_ids=(approved.pk,)), before)
        self.assertEqual(before[0]["submitted"], 1)
        self.assertEqual(before[0]["completion_percentage"], 50.0)
        submission.refresh_from_db()
        self.assertEqual(submission.product_release_id, approved.pk)
        self.assertEqual(submission.review_state, "accepted")

    def test_scope_changes_preserve_existing_job_and_aoi_provenance(self):
        delivery = Delivery.objects.create(user=self.user, filename="delivery.zip", size_bytes=12)
        job = Job.objects.create(
            delivery=delivery, requested_by=self.user, product_ident="planned_product",
            product_release=self.release, qc_definition=self.release.definition_links.get().qc_definition,
        )
        previous_aoi_ids = list(self.release.aois.values_list("pk", flat=True))
        self.approve(codes=["AT"])

        job.refresh_from_db()
        self.assertEqual(job.product_release_id, self.release.pk)
        self.assertEqual(job.qc_definition_id, self.release.definition_links.get().qc_definition_id)
        self.assertEqual(list(self.release.aois.values_list("pk", flat=True)), previous_aoi_ids)
        self.assertTrue(Delivery.objects.filter(pk=delivery.pk).exists())

    def test_form_handles_commas_and_uses_shared_canonical_codes(self):
        form = ProductDeliveryPlanForm(self.post_data(aoi_codes="CZ, cz\nSK\r\nAT"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["aoi_codes"], ["AT", "CZ", "SK"])
        self.assertEqual(list(form.cleaned_data["product_managers"]), [self.manager])
