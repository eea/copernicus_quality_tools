"""QC creation enforces reusable product policy beneath browser/API adapters."""

from dataclasses import replace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from qc_tool.common import JOB_OK
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, Job, Product, ProductRelease, ProductReleaseDefinition, QcDefinition,
)


class ProductWorkflowAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="scoped-qc-owner")
        for ident in ("first_product", "second_product"):
            UserProductGrant.objects.create(user=self.user, product_ident=ident)
        self.delivery = Delivery.objects.create(
            user=self.user, filename="unclassified.zip", size_bytes=10,
        )
        description = patch(
            "qc_tool.frontend.dashboard.services.products.find_product_description",
            return_value="Product",
        )
        self.definitions = {ident: managed_definition(ident) for ident in ("first_product", "second_product")}
        snapshot = patch(
            "qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot",
            side_effect=lambda ident, **kwargs: self.definitions.get(ident, (None, None)),
        )
        description.start()
        snapshot.start()
        self.addCleanup(description.stop)
        self.addCleanup(snapshot.stop)

    def run_qc(self, product_ident, *, access=None):
        return self.delivery.create_job(
            product_ident, "", requested_by=self.user,
            request_source="browser", account_access=access or access_for(self.user),
        )

    def test_each_assigned_product_can_run_qc_on_owned_deliveries(self):
        for ident in ("first_product", "second_product"):
            self.run_qc(ident)
            self.delivery.refresh_from_db()
            self.assertEqual(self.delivery.product_ident, ident)
            Job.objects.filter(delivery=self.delivery).update(job_status=JOB_OK)
        self.assertEqual(Job.objects.count(), 2)

    def test_unassigned_product_is_denied_before_job_or_projection_changes(self):
        with self.assertRaises(PermissionError):
            self.run_qc("unassigned_product")
        self.assertFalse(Job.objects.exists())
        self.delivery.refresh_from_db()
        self.assertIsNone(self.delivery.product_ident)

    def test_no_assignments_cannot_run_qc_on_a_generic_upload(self):
        self.user.product_grants.all().delete()
        with self.assertRaises(PermissionError):
            self.run_qc("first_product")
        self.assertFalse(Job.objects.exists())

    def test_revoked_existing_product_cannot_be_switched_to_an_assigned_product(self):
        self.run_qc("first_product")
        Job.objects.update(job_status=JOB_OK)
        self.user.product_grants.filter(product_ident="first_product").delete()

        with self.assertRaises(PermissionError):
            self.run_qc("second_product")
        self.assertEqual(Job.objects.count(), 1)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.product_ident, "first_product")

    def test_assignment_does_not_grant_ownership_or_missing_qc_capability(self):
        access = access_for(self.user)
        with self.assertRaises(PermissionError):
            self.run_qc("first_product", access=replace(
                access, permissions=access.permissions - {AccountPermission.RUN_QC},
            ))
        other = get_user_model().objects.create_user(username="another-qc-owner")
        self.delivery.user = other
        self.delivery.save(update_fields=("user",))
        with self.assertRaises(PermissionError):
            self.run_qc("first_product")
        self.assertFalse(Job.objects.exists())

    def test_restricted_token_scope_is_preserved_by_central_job_creation(self):
        access = access_for(self.user)
        token_access = access.restricted_to_snapshot(
            permissions=[permission.value for permission in access.permissions],
            roles=[role.value for role in access.roles],
            product_idents=["first_product"], is_administrator=False,
        )
        with self.assertRaises(PermissionError):
            self.run_qc("second_product", access=token_access)
        self.run_qc("first_product", access=token_access)
        self.assertEqual(Job.objects.count(), 1)

    def test_parent_assignment_requires_the_actual_job_snapshot_to_match(self):
        self.user.product_grants.all().delete()
        UserProductGrant.objects.create(user=self.user, product_ident="assigned_parent")
        product = Product.objects.create(ident="assigned_parent", name="Assigned parent")
        release = ProductRelease.objects.create(
            product=product, release_key="parent-stream", revision=1,
            catalog_digest="a" * 64, is_current=True,
        )
        definition = QcDefinition.objects.create(
            product_ident="parent_recipe", digest="b" * 64,
            document={"description": "Recipe", "steps": []},
            description="Recipe", source_path="test:recipe",
        )
        ProductReleaseDefinition.objects.create(
            product_release=release, qc_definition=definition, is_primary=True,
        )
        self.assertTrue(access_for(self.user).can_access_product("parent_recipe"))
        # A file with a different digest may no longer resolve to the release
        # that justified its presence in the product selector.
        with self.assertRaises(PermissionError):
            self.run_qc("parent_recipe")
        self.assertFalse(Job.objects.exists())

        with patch(
            "qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot",
            return_value=(definition, release),
        ):
            self.run_qc("parent_recipe")
        self.assertEqual(Job.objects.get().product_release, release)
