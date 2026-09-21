"""A complete product needs a scoped, current, explicit final confirmation."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_OK
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductReleaseDefinition,
    ProductUnit, QcDefinition, SubmissionConflict,
)
from qc_tool.frontend.dashboard.services.catalog.contracts import CatalogSyncResult
from qc_tool.frontend.dashboard.services.catalog.readiness import (
    finalize_product, product_readiness, product_readiness_many, ProductReadinessError,
)
from qc_tool.frontend.dashboard.services.catalog.specification_upload import remove_product_specification
from qc_tool.frontend.dashboard.services.catalog.sync.current_pointer import synchronize_current_pointer
from qc_tool.frontend.dashboard.services.submissions import resolve_submission_conflict


class ProductReadinessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.owner = users.create_user(username="readiness-owner")
        cls.manager = users.create_user(username="readiness-manager")
        cls.manager.groups.add(Group.objects.get(name="product_manager"))
        cls.unassigned_manager = users.create_user(username="readiness-unassigned")
        cls.unassigned_manager.groups.add(Group.objects.get(name="product_manager"))
        cls.admin = users.create_superuser(username="readiness-admin", password="password")
        cls.product = Product.objects.create(ident="ready-product", name="Readiness product")
        cls.definition = QcDefinition.objects.create(
            product_ident=cls.product.ident, digest="a" * 64, description="Readiness definition",
            document={"description": "Readiness definition", "steps": []}, source_path="fixture.json",
        )
        cls.release = cls.make_release("ready-stream")
        cls.unit = ProductUnit.objects.create(
            product_release=cls.release, product_unit_code="required-1", provenance="administrator",
        )
        for user in (cls.owner, cls.manager):
            UserProductGrant.objects.create(user=user, product_ident=cls.product.ident)

    @classmethod
    def make_release(cls, key, *, revision=1, state="authoritative", current=True):
        release = ProductRelease.objects.create(
            product=cls.product, release_key=key, revision=revision,
            catalog_digest=str(revision) * 64, description=key,
            coverage_state=state, is_current=current,
            approved_at=timezone.now() if state == "authoritative" else None,
        )
        ProductReleaseDefinition.objects.create(
            product_release=release, qc_definition=cls.definition, is_primary=True,
        )
        return release

    def candidate(self, *, unit=None, state="accepted", published=True):
        unit = unit or self.unit
        delivery = Delivery.objects.create(
            user=self.owner, filename="delivery.zip", size_bytes=1,
            product_ident=self.product.ident,
        )
        job = Job.objects.create(
            delivery=delivery, product_ident=self.product.ident,
            product_release=unit.product_release, qc_definition=self.definition, job_status=JOB_OK,
        )
        return DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=unit.product_release,
            product_unit=unit, product_unit_code=unit.product_unit_code,
            verified_product_unit_code=unit.product_unit_code, submitted_by=self.owner,
            submitted_by_username=self.owner.username, request_channel="browser",
            publication_state="published" if published else "pending",
            review_state=state, review_version=1,
            published_at=timezone.now() if published else None,
            artifact_key="retained/fixture", artifact_digest="b" * 64, input_digest="c" * 64,
        )

    def readiness(self):
        self.product.refresh_from_db()
        return product_readiness(self.product)

    def finalize(self, *, actor=None, digest=None):
        actor = actor or self.manager
        return finalize_product(
            product_ident=self.product.ident, actor=actor, account_access=access_for(actor),
            expected_scope_digest=digest or self.readiness().scope_digest,
        )

    def test_complete_coverage_requires_explicit_confirmation_and_retains_actor_audit(self):
        self.candidate()
        self.assertTrue(self.readiness().can_finalize)
        self.assertFalse(self.readiness().is_ready)
        self.client.force_login(self.manager)
        detail_url = reverse("product_detail", args=(self.product.ident,))
        page = self.client.get(detail_url)
        self.assertContains(page, "Mark product ready")
        self.assertTrue(page.context["overview"]["can_finalize"])
        self.assertContains(page, 'action="{}"'.format(reverse("product_finalize", args=(self.product.ident,))))
        digest = page.context["readiness"].scope_digest
        response = self.client.post(reverse("product_finalize", args=(self.product.ident,)), {
            "expected_scope_digest": digest,
        })
        self.assertRedirects(response, detail_url)
        self.assertTrue(self.readiness().is_ready)
        self.assertEqual(self.product.ready_by_id, self.manager.pk)
        self.assertEqual(self.product.ready_by_username, self.manager.username)
        self.assertEqual(LogEntry.objects.get().user_id, self.manager.pk)
        self.assertIn(digest, LogEntry.objects.get().change_message)
        self.finalize(digest=digest)
        self.assertEqual(LogEntry.objects.count(), 1)
        completed = self.client.get(detail_url)
        self.assertNotContains(completed, "Mark product ready")
        self.assertFalse(completed.context["overview"]["can_finalize"])
        self.assertEqual(completed.context["product_lifecycle_label"], "Completed")
        self.assertContains(completed, self.manager.username)
        self.assertNotContains(completed, "Review submissions")
        catalog = self.client.get(reverse("products"), {"product_view": "completed"})
        self.assertTrue(catalog.context["product_catalog"][0]["readiness"].is_ready)

    def test_only_assigned_manager_or_administrator_can_finalize(self):
        self.candidate()
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_product_aggregate_report",
        ))
        self.client.force_login(self.owner)
        page = self.client.get(reverse("product_detail", args=(self.product.ident,)))
        self.assertContains(page, "Awaiting final confirmation")
        self.assertNotContains(page, "Mark product ready")
        self.assertFalse(page.context["overview"]["can_finalize"])
        self.assertNotContains(page, 'action="{}"'.format(reverse("product_finalize", args=(self.product.ident,))))
        self.assertNotContains(page, "Review submissions")
        for actor in (self.owner, self.unassigned_manager):
            with self.subTest(actor=actor.username):
                with self.assertRaises(PermissionDenied):
                    self.finalize(actor=actor)
                self.client.force_login(actor)
                response = self.client.post(reverse("product_finalize", args=(self.product.ident,)), {
                    "expected_scope_digest": self.readiness().scope_digest,
                })
                self.assertEqual(response.status_code, 403)
        self.assertTrue(self.finalize(actor=self.admin).is_ready)

    def test_finalization_is_post_only_and_requires_csrf(self):
        self.candidate()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        url = reverse("product_finalize", args=(self.product.ident,))
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url, {"expected_scope_digest": self.readiness().scope_digest}).status_code, 403)
        self.assertFalse(self.readiness().is_ready)

    def test_missing_pending_rejected_or_unpublished_candidates_do_not_complete_a_unit(self):
        self.assertFalse(self.readiness().can_finalize)
        for state, published in (("pending", True), ("rejected", True), ("accepted", False)):
            self.candidate(state=state, published=published)
        self.assertEqual(self.readiness().accepted_units, 0)
        with self.assertRaises(ProductReadinessError) as error:
            self.finalize()
        self.assertEqual(error.exception.code, "product_not_complete")

    def test_every_current_release_requires_nonempty_approved_scope(self):
        self.candidate()
        for state in ("draft", "unknown", "retired", "authoritative"):
            with self.subTest(state=state):
                other = self.make_release("blocked-" + state, state=state)
                self.assertFalse(self.readiness().can_finalize)
                ProductRelease.objects.filter(pk=other.pk).update(is_current=False)
        self.assertTrue(self.readiness().can_finalize)
        ProductRelease.objects.filter(pk=self.release.pk).update(is_current=False)
        self.assertFalse(self.readiness().can_finalize)
        self.assertEqual(self.readiness().required_units, 0)

    def test_all_current_streams_count_and_historical_streams_do_not(self):
        self.candidate()
        second = self.make_release("second-stream")
        unit = ProductUnit.objects.create(
            product_release=second, product_unit_code="required-1", provenance="administrator",
        )
        self.make_release("historical-stream", current=False, state="draft")
        self.assertEqual(self.readiness().required_units, 2)
        self.assertFalse(self.readiness().can_finalize)
        self.candidate(unit=unit)
        self.assertTrue(self.readiness().can_finalize)
        with self.assertNumQueries(1):
            facts = product_readiness_many((self.product,))
        self.assertEqual(facts[self.product.pk].accepted_units, 2)

    def test_detail_keeps_accepted_units_accessible_alongside_remaining_units(self):
        self.candidate()
        pending = ProductUnit.objects.create(
            product_release=self.release, product_unit_code="required-2", provenance="administrator",
        )
        self.client.force_login(self.manager)
        url = reverse("product_detail", args=(self.product.ident,))

        response = self.client.get(url)
        plan = response.context["detail_plans"][0]
        self.assertEqual(tuple(plan["units_page"]), (pending.product_unit_code,))
        self.assertEqual(plan["units_kind"], "remaining")
        self.assertContains(response, plan["all_units_url"])
        all_units = self.client.get(url + plan["all_units_url"])
        required_plan = all_units.context["detail_plans"][0]
        self.assertEqual(required_plan["units_kind"], "required")
        self.assertEqual(tuple(required_plan["units_page"]), (self.unit.product_unit_code, pending.product_unit_code))
        self.assertEqual(all_units.context["overview"]["remaining"], 1)

        self.candidate(unit=pending)
        complete = self.client.get(url)
        completed_plan = complete.context["detail_plans"][0]
        self.assertEqual(completed_plan["units_kind"], "required")
        self.assertEqual(completed_plan["units_page"].paginator.count, 2)
        self.assertTrue(complete.context["overview"]["can_finalize"])

    def test_repeat_unreviewed_candidates_do_not_inflate_accepted_unit_count(self):
        self.candidate()
        self.candidate(state="pending")
        self.candidate(state="pending")
        self.assertTrue(self.readiness().can_finalize)
        self.assertEqual(self.readiness().accepted_units, 1)

    def test_large_plan_is_aggregated_without_materializing_unit_parameter_lists(self):
        ProductUnit.objects.bulk_create((
            ProductUnit(
                product_release=self.release, product_unit_code=f"tile-{number}",
                provenance="administrator",
            )
            for number in range(35_000)
        ), batch_size=1_000)
        with self.assertNumQueries(1):
            readiness = product_readiness(self.product)
        self.assertEqual(readiness.required_units, 35_001)
        self.assertFalse(readiness.can_finalize)

    def test_stale_or_malformed_confirmation_never_marks_ready(self):
        stale = self.readiness().scope_digest
        self.candidate()
        self.client.force_login(self.manager)
        url = reverse("product_finalize", args=(self.product.ident,))
        for digest in (stale, "", "é" * 64):
            with self.subTest(digest=digest):
                response = self.client.post(url, {"expected_scope_digest": digest})
                self.assertEqual(response.status_code, 409)
                self.assertContains(response, "accepted deliveries changed", status_code=409)
        self.assertFalse(self.readiness().is_ready)

    def test_current_pointer_change_and_restoration_cannot_resurrect_readiness(self):
        self.candidate()
        original_digest = self.readiness().scope_digest
        self.finalize()
        replacement = self.make_release(self.release.release_key, revision=2, current=False)
        synchronize_current_pointer(replacement, SimpleNamespace(
            is_current=True, release_key=replacement.release_key,
        ), CatalogSyncResult())
        self.assertFalse(self.readiness().is_ready)
        self.release.refresh_from_db()
        synchronize_current_pointer(self.release, SimpleNamespace(
            is_current=True, release_key=self.release.release_key,
        ), CatalogSyncResult())
        self.assertTrue(self.readiness().can_finalize)
        self.assertFalse(self.readiness().is_ready)
        self.assertIsNone(self.product.ready_at)
        with self.assertRaises(ProductReadinessError):
            self.finalize(digest=original_digest)

    def test_replacing_accepted_candidate_invalidates_ready_and_old_confirmation(self):
        accepted = self.candidate()
        self.finalize()
        old_digest = self.readiness().scope_digest
        replacement = self.candidate(state="conflict")
        conflict = SubmissionConflict.objects.create(
            product_unit=self.unit, version=1, opened_at=timezone.now(),
        )
        resolve_submission_conflict(
            conflict_id=conflict.pk, selected_submission_id=replacement.pk,
            actor=self.manager, account_access=access_for(self.manager), expected_version=1,
            notes="Use the corrected delivery.",
        )
        accepted.refresh_from_db()
        self.assertEqual(accepted.review_state, "rejected")
        self.assertTrue(self.readiness().can_finalize)
        self.assertFalse(self.readiness().is_ready)
        with self.assertRaises(ProductReadinessError):
            self.finalize(digest=old_digest)

    @patch("qc_tool.frontend.dashboard.services.catalog.specification_upload.publish_specification_state")
    @patch("qc_tool.frontend.dashboard.services.catalog.specification_upload.staged_specification")
    def test_archival_clears_ready_and_reactivation_needs_fresh_confirmation(self, staged, _publish):
        staged.return_value.__enter__.return_value = (None, None)
        self.candidate()
        self.finalize()
        remove_product_specification(self.product.ident, actor=self.admin)
        self.assertFalse(self.readiness().is_ready)
        self.assertIsNone(self.product.ready_at)
        Product.objects.filter(pk=self.product.pk).update(is_active=True)
        self.assertTrue(self.readiness().can_finalize)
        self.assertFalse(self.readiness().is_ready)

    def test_unreviewed_competitor_does_not_revoke_accepted_product(self):
        self.candidate()
        self.finalize()
        self.candidate(state="conflict")
        SubmissionConflict.objects.create(product_unit=self.unit, version=1, opened_at=timezone.now())
        self.assertTrue(self.readiness().is_ready)
