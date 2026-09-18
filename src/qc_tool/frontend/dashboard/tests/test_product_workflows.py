"""Products move between scoped workflow tabs as real catalog state changes."""

import hashlib

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_OK
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease,
    ProductReleaseDefinition, ProductUnit, QcDefinition,
)
from qc_tool.frontend.dashboard.services.catalog.readiness import (
    finalize_product, product_readiness,
)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ProductWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.admin = users.create_superuser(username="workflow-admin")
        cls.user = users.create_user(username="workflow-user")
        cls.user.groups.add(Group.objects.get(name="default"))
        cls.manager = users.create_user(username="workflow-manager")
        cls.manager.groups.add(Group.objects.get(name="product_manager"))

    def make_product(self, ident, *, state="authoritative", active=True):
        product = Product.objects.create(ident=ident, name=ident, is_active=active)
        release = self.make_release(product, ident, state=state)
        return product, release

    def make_release(self, product, ident, *, state="authoritative", current=True):
        digest = hashlib.sha256(ident.encode()).hexdigest()
        definition = QcDefinition.objects.create(
            product_ident=ident, digest=digest, description=ident,
            document={"description": ident, "steps": []}, source_path="fixture:" + ident,
        )
        release = ProductRelease.objects.create(
            product=product, release_key=ident, revision=1,
            catalog_digest=digest, description=ident, coverage_state=state,
            is_current=current,
            approved_at=timezone.now() if state == "authoritative" else None,
        )
        ProductReleaseDefinition.objects.create(
            product_release=release, qc_definition=definition, is_primary=True,
        )
        ProductUnit.objects.create(
            product_release=release, product_unit_code="required-1", provenance="administrator",
        )
        return release

    def accept_release(self, release):
        definition = release.definition_links.get().qc_definition
        unit = release.product_units.get()
        delivery = Delivery.objects.create(
            user=self.user, filename="delivery.zip", size_bytes=1,
            product_ident=definition.product_ident,
        )
        job = Job.objects.create(
            delivery=delivery, product_ident=definition.product_ident,
            product_release=release, qc_definition=definition, job_status=JOB_OK,
        )
        return DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=release,
            product_unit=unit, product_unit_code=unit.product_unit_code,
            submitted_product_unit_code=unit.product_unit_code, submitted_by=self.user,
            submitted_by_username=self.user.username, request_channel="browser",
            publication_state="published", review_state="accepted", review_version=1,
            published_at=timezone.now(), artifact_path="/retained/fixture",
            artifact_digest="b" * 64, input_digest="c" * 64,
        )

    def page(self, user=None, **parameters):
        self.client.force_login(user or self.admin)
        response = self.client.get(reverse("products"), parameters)
        self.assertEqual(response.status_code, 200)
        return response

    @staticmethod
    def counts(response):
        return {
            tab["value"]: tab["count"]
            for tab in response.context["product_workflow_tabs"]
        }

    @staticmethod
    def idents(response):
        return {product["ident"] for product in response.context["product_catalog"]}

    def assert_detail_workflow_links(self, product, workflow, *, user=None):
        self.client.force_login(user or self.admin)
        response = self.client.get(reverse("product_detail", args=(product.ident,)))
        self.assertEqual(response.status_code, 200)
        url = reverse("products") + "?product_view=" + workflow
        self.assertEqual(response.context["product_catalog_url"], url)
        self.assertEqual(response.context["product_workflow_label"], workflow.title())
        self.assertTemplateUsed(response, "dashboard/shared/breadcrumbs.html")
        # Both the Products breadcrumb and the back action return to this tab.
        self.assertContains(response, 'href="{}"'.format(url), count=2)
        self.assertContains(response, "Back to {} products".format(workflow))
        return response

    def test_detail_back_action_and_breadcrumb_return_to_visible_workflow_tabs(self):
        products = {}
        for workflow, state, active in (
            ("active", "authoritative", True),
            ("draft", "draft", True),
            ("stopped", "authoritative", False),
            ("completed", "authoritative", True),
        ):
            product, release = self.make_product(
                "detail-" + workflow, state=state, active=active,
            )
            UserProductGrant.objects.create(user=self.user, product_ident=product.ident)
            UserProductGrant.objects.create(user=self.manager, product_ident=product.ident)
            if workflow == "completed":
                self.accept_release(release)
                finalize_product(
                    product_ident=product.ident, actor=self.admin,
                    account_access=access_for(self.admin),
                    expected_scope_digest=product_readiness(product).scope_digest,
                )
            products[workflow] = product

        for user in (self.admin, self.user, self.manager):
            for workflow, product in products.items():
                with self.subTest(user=user.username, workflow=workflow):
                    visible_workflow = (
                        "active" if user != self.admin and workflow in ("draft", "stopped")
                        else workflow
                    )
                    self.assert_detail_workflow_links(product, visible_workflow, user=user)
                    if visible_workflow == workflow:
                        catalog = self.page(user, product_view=workflow)
                        self.assertEqual(self.idents(catalog), {product.ident})

    def test_administrator_tabs_classify_current_plans_and_keep_zero_counts_visible(self):
        self.make_product("active")
        self.make_product("draft", state="draft")
        self.make_product("undefined", state="unknown")
        self.make_product("stopped", active=False)
        self.make_product("retired", state="retired")
        mixed, _ = self.make_product("mixed")
        self.make_release(mixed, "mixed-retired", state="retired")
        historical, _ = self.make_product("historical")
        self.make_release(historical, "old-draft", state="draft", current=False)

        response = self.page()
        self.assertEqual(response.context["product_view"], "active")
        self.assertEqual(self.idents(response), {"active", "historical"})
        self.assertEqual(self.counts(response), {
            "active": 2, "draft": 3, "stopped": 2, "completed": 0,
        })
        self.assertEqual(response.context["total_product_count"], 7)
        self.assertEqual(self.idents(self.page(product_view="draft")), {
            "draft", "undefined", "mixed",
        })
        self.assertEqual(self.idents(self.page(product_view="stopped")), {
            "stopped", "retired",
        })
        self.assertEqual(self.idents(self.page(product_view="completed")), set())

    def test_empty_catalog_navigation_uses_catalog_management_permission(self):
        response = self.page(self.admin)
        self.assertEqual(self.counts(response), {
            "active": 0, "draft": 0, "stopped": 0, "completed": 0,
        })
        for user in (self.user, self.manager):
            with self.subTest(user=user.username):
                response = self.page(user)
                self.assertEqual(self.counts(response), {"active": 0})
                for workflow in ("draft", "stopped", "completed"):
                    self.assertNotContains(response, "?product_view=" + workflow)

    def test_accepted_scope_needs_manager_confirmation_and_stale_readiness_is_active(self):
        product, release = self.make_product("ready-product")
        UserProductGrant.objects.create(user=self.manager, product_ident=product.ident)
        accepted = self.accept_release(release)
        response = self.page()
        self.assertEqual(self.idents(response), {product.ident})
        self.assertTrue(response.context["product_catalog"][0]["readiness"].can_finalize)
        self.assertEqual(self.counts(response)["completed"], 0)

        finalize_product(
            product_ident=product.ident, actor=self.manager,
            account_access=access_for(self.manager),
            expected_scope_digest=product_readiness(product).scope_digest,
        )
        self.assertEqual(self.idents(self.page(product_view="completed")), {product.ident})
        self.assertEqual(self.idents(self.page()), set())

        # Even an old stored ready timestamp cannot turn changed accepted scope
        # into a completion. The existing readiness service validates its digest.
        DeliverySubmission.objects.filter(pk=accepted.pk).update(review_state="rejected")
        self.assertEqual(self.idents(self.page()), {product.ident})
        self.assertEqual(self.counts(self.page())["completed"], 0)

    def test_full_assignment_sees_lifecycle_without_hidden_coverage_totals(self):
        product, release = self.make_product("assigned-ready")
        self.make_product("unassigned-draft", state="draft")
        UserProductGrant.objects.create(user=self.user, product_ident=product.ident)
        self.accept_release(release)
        finalize_product(
            product_ident=product.ident, actor=self.admin, account_access=access_for(self.admin),
            expected_scope_digest=product_readiness(product).scope_digest,
        )
        response = self.page(self.user, product_view="completed")
        self.assertEqual(self.counts(response), {
            "active": 0, "completed": 1,
        })
        self.assertEqual(self.idents(response), {product.ident})
        row = response.context["product_catalog"][0]
        self.assertFalse(row["can_view_coverage"])
        for field in ("expected", "accepted", "completion_percentage", "readiness"):
            self.assertIsNone(row[field])

    def test_partial_recipe_assignment_does_not_leak_other_stream_state_or_completion(self):
        product, assigned = self.make_product("parent")
        hidden = self.make_release(product, "hidden-recipe", state="draft")
        UserProductGrant.objects.create(user=self.manager, product_ident="parent")
        # A parent grant would authorize every stream; use a separate recipe
        # identity so the account can only classify its own stream.
        assigned.definition_links.all().delete()
        definition = QcDefinition.objects.create(
            product_ident="assigned-recipe", digest="d" * 64,
            description="Assigned recipe", document={"steps": []}, source_path="fixture",
        )
        ProductReleaseDefinition.objects.create(
            product_release=assigned, qc_definition=definition, is_primary=True,
        )
        UserProductGrant.objects.filter(user=self.manager).update(product_ident="assigned-recipe")
        response = self.page(self.manager)
        self.assertEqual(self.idents(response), {product.ident})
        self.assertEqual(self.counts(response), {"active": 1})
        self.assertFalse(response.context["product_catalog"][0]["can_view_coverage"])
        detail = self.assert_detail_workflow_links(product, "active", user=self.manager)
        self.assertIsNone(detail.context["readiness"])

        ProductRelease.objects.filter(pk=hidden.pk).update(
            coverage_state="authoritative", approved_at=timezone.now(),
        )
        hidden.refresh_from_db()
        self.accept_release(assigned)
        self.accept_release(hidden)
        finalize_product(
            product_ident=product.ident, actor=self.admin, account_access=access_for(self.admin),
            expected_scope_digest=product_readiness(product).scope_digest,
        )
        self.assertEqual(self.counts(self.page(self.manager)), self.counts(response))
        self.assertRedirects(
            self.client.get(reverse("products"), {"product_view": "completed"}),
            reverse("products"),
        )
        detail = self.assert_detail_workflow_links(product, "active", user=self.manager)
        self.assertIsNone(detail.context["readiness"])

    def test_hidden_tabs_and_legacy_stopped_links_redirect_to_active(self):
        stopped, _ = self.make_product("assigned-stopped", active=False)
        draft, _ = self.make_product("assigned-draft", state="draft")
        self.make_product("unassigned-stopped", active=False)
        for user in (self.user, self.manager):
            for product in (stopped, draft):
                UserProductGrant.objects.create(user=user, product_ident=product.ident)
            response = self.page(user)
            self.assertEqual(self.counts(response), {"active": 0})
            for parameters in (
                {"product_view": "draft"}, {"product_view": "stopped"},
                {"product_view": "completed"}, {"archived": "1"},
            ):
                with self.subTest(user=user.username, parameters=parameters):
                    self.assertRedirects(
                        self.client.get(reverse("products"), parameters), reverse("products"),
                    )
        response = self.page(archived="1", product_view="active")
        self.assertEqual(response.context["product_view"], "active")

    def test_completed_tab_requires_a_completed_product_in_account_scope(self):
        visible, _ = self.make_product("assigned-active")
        completed, release = self.make_product("completed")
        self.accept_release(release)
        finalize_product(
            product_ident=completed.ident, actor=self.admin,
            account_access=access_for(self.admin),
            expected_scope_digest=product_readiness(completed).scope_digest,
        )
        for user in (self.user, self.manager):
            UserProductGrant.objects.create(user=user, product_ident=visible.ident)
            response = self.page(user)
            self.assertEqual(self.counts(response), {"active": 1})
            self.assertEqual(self.idents(response), {visible.ident})
            self.assertNotContains(response, "?product_view=completed")
            self.assertRedirects(
                self.client.get(reverse("products"), {"product_view": "completed"}),
                reverse("products"),
            )

            grant = UserProductGrant.objects.create(user=user, product_ident=completed.ident)
            response = self.page(user, product_view="completed")
            self.assertEqual(self.counts(response), {"active": 1, "completed": 1})
            self.assertEqual(self.idents(response), {completed.ident})
            self.assertContains(response, "?product_view=completed")

            grant.delete()
            response = self.page(user)
            self.assertEqual(self.counts(response), {"active": 1})
            self.assertNotContains(response, "?product_view=completed")

    def test_unassigned_user_has_no_counts_and_invalid_views_fail_closed(self):
        self.make_product("hidden")
        response = self.page(self.user)
        self.assertEqual(response.context["total_product_count"], 0)
        self.assertTrue(all(count == 0 for count in self.counts(response).values()))
        self.assertEqual(self.idents(response), set())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("products"), {"product_view": "all"}).status_code, 400)
