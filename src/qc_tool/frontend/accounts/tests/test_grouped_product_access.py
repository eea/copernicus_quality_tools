"""Catalog assignments retain product boundaries across shared QC recipes."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.product_grants import create_product_grant
from qc_tool.frontend.accounts.services.products import product_ident_choices
from qc_tool.frontend.dashboard.access.deliveries import can_view_delivery
from qc_tool.frontend.dashboard.access.delivery_querysets import visible_deliveries
from qc_tool.frontend.dashboard.models import (
    Delivery, Job, Product, ProductRelease, ProductReleaseDefinition, QcDefinition,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.query import query_deliveries


class GroupedProductAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = get_user_model().objects.create_user(username="grouped-manager")
        cls.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        cls.owner = get_user_model().objects.create_user(username="grouped-uploader")
        cls.product = Product.objects.create(ident="grouped_product", name="Grouped product")
        cls.other = Product.objects.create(ident="unassigned_product", name="Unassigned product")
        cls.first = cls.make_release(cls.product, "first_stream", "shared_recipe")
        cls.second = cls.make_release(cls.product, "second_stream", "second_recipe")
        cls.unassigned = cls.make_release(cls.other, "unassigned_stream", "shared_recipe")

    @classmethod
    def make_release(cls, product, key, recipe):
        definition, _ = QcDefinition.objects.get_or_create(
            product_ident=recipe, digest="a" * 64,
            defaults={"description": recipe, "document": {"description": recipe, "steps": []}, "source_path": "test:recipe"},
        )
        release = ProductRelease.objects.create(
            product=product, release_key=key, revision=1, description=key,
            catalog_digest="b" * 64, is_current=True,
        )
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        return release

    def grant(self, *idents):
        for ident in idents:
            UserProductGrant.objects.create(user=self.manager, product_ident=ident)
        return access_for(self.manager)

    def delivery(self, release, filename):
        definition = release.definition_links.get().qc_definition
        delivery = Delivery.objects.create(
            user=self.owner, filename=filename, size_bytes=1,
            product_ident=definition.product_ident,
        )
        Job.objects.create(
            delivery=delivery, product_ident=definition.product_ident,
            product_release=release, qc_definition=definition,
        )
        return delivery

    def test_parent_grant_covers_all_streams_without_granting_shared_recipe_products(self):
        access = self.grant("grouped_product")

        self.assertEqual(access.product_idents, {"grouped_product"})
        self.assertTrue(access.can_browse_product("grouped_product"))
        self.assertTrue(access.can_view_product_report("grouped_product"))
        self.assertTrue(access.can_review_product_submission("grouped_product"))
        self.assertFalse(access.can_browse_product("unassigned_product"))
        self.assertFalse(access.can_view_product_report("unassigned_product"))
        self.assertFalse(access.can_review_product_submission("unassigned_product"))
        self.assertNotIn("shared_recipe", access.product_idents)

    def test_partial_recipe_grant_does_not_reveal_other_streams_or_allow_their_review(self):
        access = self.grant("shared_recipe")

        self.assertTrue(access.can_browse_product("grouped_product"))
        self.assertFalse(access.can_view_product_report("grouped_product"))
        self.assertFalse(access.can_review_product_submission("grouped_product"))
        self.assertTrue(access.can_review_product_submission("unassigned_product"))
        self.assertEqual(access.product_idents, {"shared_recipe"})

    def test_all_recipe_grants_allow_complete_parent_reporting_and_review(self):
        access = self.grant("shared_recipe", "second_recipe")

        self.assertTrue(access.can_view_product_report("grouped_product"))
        self.assertTrue(access.can_review_product_submission("grouped_product"))
        self.assertIn("grouped_product", access.reviewable_product_idents)

    def test_new_stream_removes_derived_complete_scope_until_it_is_assigned(self):
        access = self.grant("shared_recipe", "second_recipe")
        self.assertTrue(access.can_view_product_report("grouped_product"))
        self.make_release(self.product, "third_stream", "third_recipe")

        refreshed = access_for(self.manager)
        self.assertFalse(refreshed.can_view_product_report("grouped_product"))
        self.assertFalse(refreshed.can_review_product_submission("grouped_product"))
        self.assertTrue(refreshed.can_browse_product("grouped_product"))

    def test_token_snapshot_recomputes_derived_scope_from_its_restricted_raw_grants(self):
        access = self.grant("shared_recipe", "second_recipe")
        restricted = access.restricted_to_snapshot(
            permissions=[permission.value for permission in access.permissions],
            roles=[role.value for role in access.roles], region_codes=[],
            product_idents=["shared_recipe"], is_administrator=False,
        )

        self.assertEqual(restricted.product_idents, {"shared_recipe"})
        self.assertFalse(restricted.can_view_product_report("grouped_product"))
        self.assertFalse(restricted.can_review_product_submission("grouped_product"))
        self.assertTrue(restricted.can_browse_product("grouped_product"))

    def test_current_recipe_grants_do_not_authorize_unassigned_historical_submissions(self):
        historical = self.make_release(self.product, "historical_stream", "historical_recipe")
        historical.is_current = False
        historical.save(update_fields=("is_current",))
        access = self.grant("shared_recipe", "second_recipe")

        self.assertTrue(access.can_view_product_report("grouped_product"))
        self.assertFalse(access.can_review_product_submission("grouped_product"))
        self.assertNotIn("grouped_product", access.reviewable_product_idents)

    def test_parent_assignment_matches_object_orm_and_sql_delivery_visibility(self):
        access = self.grant("grouped_product")
        first = self.delivery(self.first, "first.zip")
        second = self.delivery(self.second, "second.zip")
        outside = self.delivery(self.unassigned, "outside.zip")

        self.assertTrue(can_view_delivery(access, first))
        self.assertTrue(can_view_delivery(access, second))
        self.assertFalse(can_view_delivery(access, outside))
        self.assertEqual(set(visible_deliveries(access).values_list("pk", flat=True)), {first.pk, second.pk})
        count, rows = query_deliveries(self.manager, account_access=access)
        self.assertEqual(count, 2)
        self.assertEqual({row["id"] for row in rows}, {first.pk, second.pk})

    def test_parent_delivery_scope_follows_the_latest_job_not_an_older_assigned_job(self):
        access = self.grant("grouped_product")
        delivery = self.delivery(self.first, "rechecked.zip")
        Job.objects.create(
            delivery=delivery, product_ident="shared_recipe",
            product_release=self.unassigned,
            qc_definition=self.unassigned.definition_links.get().qc_definition,
        )

        self.assertFalse(can_view_delivery(access, delivery))
        self.assertFalse(visible_deliveries(access).filter(pk=delivery.pk).exists())
        self.assertEqual(query_deliveries(self.manager, account_access=access)[0], 0)

    @patch("qc_tool.frontend.accounts.services.products.get_product_descriptions", return_value={"shared_recipe": "Shared recipe"})
    def test_admin_grant_selectors_accept_catalog_products_without_adding_them_to_qc_choices(self, _descriptions):
        from qc_tool.frontend.accounts.services.products import available_product_descriptions

        self.assertIn("grouped_product", dict(product_ident_choices()))
        grant = create_product_grant(user=self.manager, product_ident="grouped_product")
        self.assertEqual(grant.product_ident, "grouped_product")
        self.assertNotIn("grouped_product", available_product_descriptions())
