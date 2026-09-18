"""Catalog assignments retain product boundaries across shared QC recipes."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant, UserProfile, UserRegionGrant
from qc_tool.frontend.accounts.services.product_grants import create_product_grant
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.accounts.services.products import product_ident_choices
from qc_tool.frontend.dashboard.access.deliveries import can_view_delivery
from qc_tool.frontend.dashboard.access.deliveries import delivery_product_scope_matches
from qc_tool.frontend.dashboard.access.jobs import can_view_job
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

    def assert_owner_visibility(self, visible, hidden=()):
        access = access_for(self.owner)
        expected = {delivery.pk for delivery in visible}
        for delivery in visible:
            self.assertTrue(can_view_delivery(access, delivery))
        for delivery in hidden:
            self.assertFalse(can_view_delivery(access, delivery))
        self.assertEqual(set(visible_deliveries(access).values_list("pk", flat=True)), expected)
        count, rows = query_deliveries(
            self.owner, account_access=access, include_capabilities=True,
        )
        self.assertEqual(count, len(expected))
        self.assertEqual({row["id"] for row in rows}, expected)
        return rows

    def test_default_owner_grant_limits_objects_orm_sql_and_actions(self):
        UserProductGrant.objects.create(user=self.owner, product_ident="grouped_product")
        first = self.delivery(self.first, "owner-first.zip")
        second = self.delivery(self.second, "owner-second.zip")
        outside = self.delivery(self.unassigned, "owner-outside.zip")

        rows = self.assert_owner_visibility([first, second], [outside])
        for row in rows:
            self.assertTrue(row["can_run_qc"])
            self.assertTrue(row["can_submit"])
            self.assertTrue(row["can_delete"])

        self.owner.product_grants.all().delete()
        self.assert_owner_visibility([], [first, second, outside])

    def test_default_owner_can_have_multiple_exact_recipe_assignments(self):
        UserProductGrant.objects.bulk_create([
            UserProductGrant(user=self.owner, product_ident="shared_recipe"),
            UserProductGrant(user=self.owner, product_ident="second_recipe"),
        ])
        first = self.delivery(self.first, "recipe-first.zip")
        second = self.delivery(self.second, "recipe-second.zip")
        shared = self.delivery(self.unassigned, "recipe-shared.zip")
        self.assert_owner_visibility([first, second, shared])

    def test_parent_assignment_handles_unambiguous_pre_qc_recipe_only(self):
        UserProductGrant.objects.create(user=self.owner, product_ident="grouped_product")
        unique = Delivery.objects.create(
            user=self.owner, filename="unique-before-qc.zip", size_bytes=1,
            product_ident=" SECOND_RECIPE ",
        )
        shared = Delivery.objects.create(
            user=self.owner, filename="shared-before-qc.zip", size_bytes=1,
            product_ident="shared_recipe",
        )
        self.assert_owner_visibility([unique], [shared])

    def test_default_owner_parent_scope_follows_latest_selected_release(self):
        UserProductGrant.objects.create(user=self.owner, product_ident="grouped_product")
        delivery = self.delivery(self.first, "owner-rechecked.zip")
        self.assert_owner_visibility([delivery])
        Job.objects.create(
            delivery=delivery, product_ident="shared_recipe",
            product_release=self.unassigned,
            qc_definition=self.unassigned.definition_links.get().qc_definition,
        )
        self.assert_owner_visibility([], [delivery])

    def test_unidentified_uploads_need_an_assignment_and_existing_jobs_remain_scoped(self):
        unknown = Delivery.objects.create(
            user=self.owner, filename="unknown.zip", size_bytes=1,
        )
        blank = Delivery.objects.create(
            user=self.owner, filename="blank.zip", size_bytes=1, product_ident="  ",
        )
        self.assert_owner_visibility([], [unknown, blank])
        UserProductGrant.objects.create(user=self.owner, product_ident="grouped_product")
        self.assert_owner_visibility([unknown, blank])
        Job.objects.create(
            delivery=unknown, product_ident="shared_recipe",
            product_release=self.unassigned,
        )
        self.assert_owner_visibility([blank], [unknown])
        UserProductGrant.objects.create(user=self.owner, product_ident="shared_recipe")
        self.assert_owner_visibility([unknown, blank])

    def test_region_visible_unassigned_owner_delivery_has_no_mutation_actions(self):
        UserProductGrant.objects.create(user=self.owner, product_ident="grouped_product")
        UserProfile.objects.create(user=self.owner, country="CZ")
        UserRegionGrant.objects.create(user=self.owner, region_code="CZ")
        self.owner.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))
        outside = self.delivery(self.unassigned, "regional-unassigned.zip")
        rows = self.assert_owner_visibility([outside])
        self.assertFalse(delivery_product_scope_matches(access_for(self.owner), outside))
        self.assertFalse(rows[0]["can_run_qc"])
        self.assertFalse(rows[0]["can_submit"])
        self.assertFalse(rows[0]["can_delete"])

    def test_product_manager_grant_does_not_reveal_other_users_unidentified_uploads(self):
        access = self.grant("grouped_product")
        delivery = Delivery.objects.create(user=self.owner, filename="private.zip", size_bytes=1)
        self.assertFalse(can_view_delivery(access, delivery))
        self.assertFalse(visible_deliveries(access).exists())
        self.assertEqual(query_deliveries(self.manager, account_access=access)[0], 0)

    def test_historical_jobs_keep_their_recorded_scope_after_an_owner_grant_is_revoked(self):
        UserProductGrant.objects.bulk_create([
            UserProductGrant(user=self.owner, product_ident=ident)
            for ident in ("grouped_product", "unassigned_product")
        ])
        delivery = self.delivery(self.unassigned, "historical-private.zip")
        old_job = delivery.job_set.get()
        latest_job = Job.objects.create(
            delivery=delivery, product_ident="shared_recipe",
            product_release=self.first,
        )
        token = issue_personal_access_token(self.owner, "History scope regression")
        self.owner.product_grants.filter(product_ident="unassigned_product").delete()
        access = access_for(self.owner)

        self.assertTrue(can_view_delivery(access, delivery))
        self.assertTrue(can_view_job(access, latest_job))
        self.assertFalse(can_view_job(access, old_job))
        self.client.force_login(self.owner)
        for name in ("show_result", "job_report_json", "job_report_pdf", "job_combined_log"):
            with self.subTest(endpoint=name):
                self.assertEqual(self.client.get(reverse(name, args=(old_job.pk,))).status_code, 403)
        self.assertEqual(self.client.post(reverse("update_job", args=(old_job.pk,))).status_code, 403)
        history = self.client.get(reverse("job_history_json", args=(delivery.pk,)))
        self.assertEqual([row["job_uuid"] for row in history.json()], [str(latest_job.pk)])
        api_history = self.client.get(
            reverse("api_job_history", args=(delivery.pk,)),
            HTTP_AUTHORIZATION=f"Bearer {token.raw_token}",
        )
        self.assertEqual(api_history.status_code, 200)
        self.assertEqual([row["job_uuid"] for row in api_history.json()["data"]], [latest_job.pk.hex])

    def test_historical_job_product_scope_preserves_explicit_region_read_access(self):
        delivery = self.delivery(self.unassigned, "region-history.zip")
        job = delivery.job_set.get()
        UserProfile.objects.create(user=self.owner, country="CZ")
        UserRegionGrant.objects.create(user=self.manager, region_code="CZ")
        self.manager.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))
        self.assertTrue(can_view_job(access_for(self.manager), job))

    @patch("qc_tool.frontend.accounts.services.products.available_product_descriptions", return_value={"shared_recipe": "Shared recipe"})
    def test_admin_grant_selectors_accept_catalog_products_without_adding_them_to_qc_choices(self, _descriptions):
        from qc_tool.frontend.accounts.services.products import available_product_descriptions

        self.assertIn("grouped_product", dict(product_ident_choices()))
        grant = create_product_grant(user=self.manager, product_ident="grouped_product")
        self.assertEqual(grant.product_ident, "grouped_product")
        self.assertNotIn("grouped_product", available_product_descriptions())
