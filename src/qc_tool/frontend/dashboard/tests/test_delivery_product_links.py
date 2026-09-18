"""Delivery navigation follows selected catalog context and viewer access."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_OK
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant, UserProfile, UserRegionGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductUnit,
    ProductRelease, ProductReleaseDefinition, QcDefinition,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import query_deliveries
from qc_tool.frontend.dashboard.views.deliveries.listing.links import add_delivery_links


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryProductLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="product-link-owner")
        UserProductGrant.objects.bulk_create([
            UserProductGrant(user=cls.owner, product_ident=ident)
            for ident in (
                "shared-recipe", "first-product", "missing-product",
                "historical-product", "no-release-product",
            )
        ])
        cls.manager = get_user_model().objects.create_user(username="product-link-manager")
        cls.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        cls.definition = QcDefinition.objects.create(
            product_ident="shared-recipe", digest="a" * 64,
            description="Recorded QC recipe", document={"steps": []}, source_path="test.json",
        )
        cls.first = cls.create_release("first-product")
        cls.second = cls.create_release("second-product")

    @classmethod
    def create_release(cls, ident, *, is_current=True):
        product = Product.objects.create(ident=ident, name=ident.replace("-", " ").title())
        release = ProductRelease.objects.create(
            product=product, release_key=ident + "-v1", revision=1,
            catalog_digest="b" * 64, is_current=is_current,
        )
        ProductReleaseDefinition.objects.create(
            product_release=release, qc_definition=cls.definition, is_primary=True,
        )
        return release

    def create_delivery(self, filename, *, owner=None, ident="shared-recipe"):
        return Delivery.objects.create(
            user=owner or self.owner, filename=filename, size_bytes=123,
            product_ident=ident, product_description="Recorded QC recipe",
        )

    def create_job(self, delivery, release, *, created_at=None):
        return Job.objects.create(
            delivery=delivery, product_release=release, qc_definition=self.definition,
            product_ident=self.definition.product_ident, job_status=JOB_OK,
            date_created=created_at or timezone.now(),
        )

    def create_submission(self, delivery, job):
        aoi = ProductUnit.objects.create(
            product_release=job.product_release, product_unit_code="CZ", provenance="manifest",
        )
        return DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=job.product_release,
            product_unit=aoi, product_unit_code="CZ", submitted_product_unit_code="CZ",
            submitted_by=delivery.user, submitted_by_username=delivery.user.username,
            request_channel="browser",
        )

    def rows(self, user=None):
        user = user or self.owner
        access = access_for(user)
        rows = query_deliveries(user, account_access=access)[1]
        return add_delivery_links(rows, access)

    def assert_history_destination(self, delivery, row, user=None):
        self.client.force_login(user or self.owner)
        response = self.client.get(reverse("job_history", args=(delivery.pk,)))
        self.assertEqual(response.status_code, 200)
        summary = response.context["delivery_summary"]
        self.assertEqual(summary["description_url"], row["product_url"])
        self.assertEqual(
            summary["description"],
            row["product_display_name"] or delivery.product_description,
        )
        return summary

    def test_json_uses_latest_selected_parent_and_preserves_recorded_recipe(self):
        delivery = self.create_delivery("latest-parent.zip")
        self.create_job(delivery, self.first, created_at=timezone.now() - timedelta(minutes=1))
        job = self.create_job(delivery, self.second)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("deliveries_json"))

        self.assertEqual(response.status_code, 200)
        row = response.json()["rows"][0]
        self.assertEqual(row["product_ident"], "shared-recipe")
        self.assertEqual(row["product_description"], "Recorded QC recipe")
        self.assertEqual(row["product_display_name"], self.second.product.name)
        self.assertEqual(row["product_url"], reverse("product_detail", args=(self.second.product.ident,)))
        self.assertEqual(row["job_result_url"], reverse("show_result", args=(job.pk,)))
        self.assertEqual(self.client.get(row["product_url"]).status_code, 200)
        self.assert_history_destination(delivery, row)

    def test_submission_parent_remains_authoritative_if_latest_job_differs(self):
        delivery = self.create_delivery("submitted-parent.zip")
        submitted_job = self.create_job(
            delivery, self.first, created_at=timezone.now() - timedelta(minutes=1),
        )
        submission = self.create_submission(delivery, submitted_job)
        self.create_job(delivery, self.second)

        row = self.rows()[0]

        self.assertEqual(row["submission_id"], str(submission.pk))
        self.assertEqual(row["product_url"], reverse("product_detail", args=(self.first.product.ident,)))
        self.assertEqual(row["product_display_name"], self.first.product.name)
        self.assert_history_destination(delivery, row)

    def test_unvalidated_deliveries_link_only_exact_available_catalog_identities(self):
        for name, ident in (
            ("ambiguous.zip", "shared-recipe"),
            ("unknown.zip", "missing-product"),
            ("unidentified.zip", None),
            ("exact.zip", "FIRST-PRODUCT"),
        ):
            self.create_delivery(name, ident=ident)
        historical = self.create_release("historical-product", is_current=False)
        self.create_delivery("historical.zip", ident=historical.product.ident)
        Product.objects.create(ident="no-release-product", name="No release product")
        self.create_delivery("no-release.zip", ident="no-release-product")

        rows = {row["filename"]: row for row in self.rows()}

        self.assertEqual(rows["exact.zip"]["product_url"], reverse("product_detail", args=(self.first.product.ident,)))
        for name, row in rows.items():
            if name != "exact.zip":
                with self.subTest(filename=name):
                    self.assertEqual(row["product_url"], "")
                    self.assertEqual(row["product_display_name"], "")
            self.assert_history_destination(Delivery.objects.get(pk=row["id"]), row)

    def test_unavailable_selected_parent_does_not_fall_back_to_a_different_product(self):
        retired = self.create_release("old-selected-product", is_current=False)
        delivery = self.create_delivery("selected-retired.zip", ident=self.first.product.ident)
        self.create_job(delivery, retired)

        row = self.rows()[0]

        self.assertEqual(row["product_url"], "")
        self.assertEqual(row["product_display_name"], "")
        self.assert_history_destination(delivery, row)

    def test_own_delivery_does_not_grant_manager_access_to_unassigned_product(self):
        delivery = self.create_delivery("manager-owned.zip", owner=self.manager)
        self.create_job(delivery, self.first)

        self.assertEqual(self.rows(self.manager), [])
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(
            reverse("job_history", args=(delivery.pk,)),
        ).status_code, 403)
        UserProductGrant.objects.create(user=self.manager, product_ident=self.first.product.ident)
        row = self.rows(self.manager)[0]
        self.assertEqual(row["product_url"], reverse("product_detail", args=(self.first.product.ident,)))
        self.assert_history_destination(delivery, row, self.manager)

    def test_history_region_viewer_does_not_use_private_submission_context(self):
        delivery = self.create_delivery("private-submission-parent.zip")
        submitted_job = self.create_job(
            delivery, self.first, created_at=timezone.now() - timedelta(minutes=1),
        )
        self.create_submission(delivery, submitted_job)
        self.create_job(delivery, self.second)
        viewer = get_user_model().objects.create_user(username="product-link-region-viewer")
        UserProfile.objects.create(user=self.owner, country="CZ")
        UserRegionGrant.objects.create(user=viewer, region_code="CZ")
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))
        UserProductGrant.objects.create(user=viewer, product_ident=self.second.product.ident)

        row = self.rows(viewer)[0]

        self.assertIsNone(row["submission_id"])
        self.assertEqual(row["product_display_name"], self.second.product.name)
        self.assert_history_destination(delivery, row, viewer)

    def test_link_projection_uses_bounded_bulk_queries_for_the_whole_page(self):
        for index in range(6):
            delivery = self.create_delivery(f"bulk-{index}.zip")
            job = self.create_job(delivery, self.first)
            if index == 0:
                self.create_submission(delivery, job)
        access = access_for(self.owner)
        rows = query_deliveries(self.owner, account_access=access)[1]
        access.browsable_product_idents

        with self.assertNumQueries(3):
            add_delivery_links(rows, access)

        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["product_url"] for row in rows))
