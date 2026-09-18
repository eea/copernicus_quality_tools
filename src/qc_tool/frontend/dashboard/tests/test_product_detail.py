"""Public contracts for the Products workspace hierarchy and detail page."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.test import TestCase
from django.test import override_settings
from django.urls import resolve
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition
from qc_tool.frontend.dashboard.models import QcDefinition
from qc_tool.frontend.dashboard.services.products.lookup import (
    MAX_CURRENT_RELEASES,
)
from qc_tool.frontend.dashboard.views.products.catalog import (
    _aggregate_coverage,
    _plan_presentation,
)
from qc_tool.frontend.dashboard.views.products.data import (
    get_product_definition,
)


PRODUCT_IDENT = "clms_ua_lcuc_c2021-2024_v010ha"
OTHER_PRODUCT_IDENT = "clms_test_other_product"


class ProductPlanPresentationTests(SimpleTestCase):
    def test_plan_labels_distinguish_provisional_and_approved_scope(self):
        for states, expected, status, label, progress_hint in (
            (("authoritative",), 2, "approved", "Approved", None),
            (("authoritative",), 0, "approved", "Approved", "No product units in the approved plan"),
            (("draft",), None, "draft", "Draft", "Awaiting plan approval"),
            (("unknown",), None, "undefined", "Not defined", "Define expected product units"),
            (("draft", "authoritative"), None, "mixed", "Mixed plans", "Review release plans"),
            (("unknown", "draft"), None, "mixed", "Mixed plans", "Review release plans"),
            (("retired",), None, "retired", "Retired", "Plan retired"),
            ((), None, "undefined", "Not defined", "Define expected product units"),
        ):
            with self.subTest(states=states, expected=expected):
                display = _plan_presentation(
                    {
                        "can_view_coverage": True,
                        "expected": expected,
                        "declared_expected": expected,
                        "releases": tuple(
                            {"coverage_state": state} for state in states
                        ),
                    },
                    managed=bool(states),
                )

                self.assertEqual(display["plan_status"], status)
                self.assertEqual(display["plan_label"], label)
                if progress_hint:
                    self.assertEqual(display["progress_hint"], progress_hint)

    def test_restricted_plan_metadata_does_not_reveal_release_states(self):
        presentations = [
            _plan_presentation(
                {
                    "can_view_coverage": False,
                    "expected": None,
                    "releases": ({"coverage_state": state},),
                },
                managed=True,
            )
            for state in ("authoritative", "draft", "unknown", "retired")
        ]

        self.assertTrue(all(item == presentations[0] for item in presentations))
        self.assertEqual(presentations[0]["plan_status"], "restricted")
        self.assertEqual(presentations[0]["progress_hint"], "Coverage restricted")


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ProductDetailRoutingTests(TestCase):
    def test_product_routes_have_an_unambiguous_hierarchy(self):
        detail_path = reverse(
            "product_detail",
            kwargs={"product_ident": PRODUCT_IDENT},
        )

        self.assertEqual(detail_path, "/products/{}/".format(PRODUCT_IDENT))
        self.assertEqual(reverse("product_list_json"), "/products/list/")
        self.assertEqual(
            resolve("/products/list/").url_name,
            "product_list_json",
        )
        self.assertEqual(resolve(detail_path).url_name, "product_detail")


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class EmptyProductDetailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="empty-catalog-admin", email="admin@example.test",
            password="test-password",
        )
        self.client.force_login(self.user)

    @patch(
        "qc_tool.common.load_product_definition",
        side_effect=AssertionError("Catalog pages must not discover bundled files"),
    )
    def test_empty_catalog_does_not_expose_bundled_product_details(self, loader):
        response = self.client.get(reverse("products"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["product_count"], 0)
        self.assertContains(response, "Add your first product")
        for ident in (PRODUCT_IDENT, "unknown_product", PRODUCT_IDENT.upper()):
            with self.subTest(ident=ident):
                detail = self.client.get(reverse("product_detail", args=(ident,)))
                self.assertEqual(detail.status_code, 404)
        loader.assert_not_called()

    def test_definition_data_route_normalizes_legacy_uppercase_identifiers(self):
        managed_definition("product")
        with TemporaryDirectory() as directory:
            definition_path = Path(directory, "product.json")
            definition_path.write_text("{}", encoding="utf-8")
            with patch(
                "qc_tool.frontend.dashboard.views.products.data."
                "locate_product_definition",
                return_value=definition_path,
            ) as locate_definition:
                request = RequestFactory().get(
                    reverse("product_definition_json", args=("PRODUCT",)),
                )
                request.user = self.user
                response = get_product_definition(request, "PRODUCT")

                self.assertEqual(response.status_code, 200)
                locate_definition.assert_called_once_with("product")
                response.file_to_stream.close()


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ManagedProductDetailAccessTests(TestCase):
    def setUp(self):
        self.default_user = get_user_model().objects.create_user(
            username="product-detail-default-user",
            password="test-password",
        )
        UserProductGrant.objects.create(user=self.default_user, product_ident=PRODUCT_IDENT)
        UserProductGrant.objects.create(user=self.default_user, product_ident=OTHER_PRODUCT_IDENT)
        self.product, self.release = self.create_product_release(
            PRODUCT_IDENT,
            name="Managed Urban Atlas",
            product_unit_codes=("cz001l", "cz002l"),
        )
        self.other_product, self.other_release = self.create_product_release(
            OTHER_PRODUCT_IDENT,
            name="Other managed product",
            product_unit_codes=("de001l",),
        )

    def create_product_release(self, product_ident, *, name, product_unit_codes):
        product = Product.objects.create(
            ident=product_ident,
            name=name,
            description="{} description".format(name),
        )
        release = self.create_release(
            product,
            release_key="{}_release".format(product_ident),
            description="{} release".format(name),
            product_unit_codes=product_unit_codes,
        )
        return product, release

    def create_release(
        self,
        product,
        *,
        release_key,
        description,
        product_unit_codes=(),
        coverage_state=ProductRelease.CoverageState.AUTHORITATIVE,
    ):
        release = ProductRelease.objects.create(
            product=product,
            release_key=release_key,
            revision=1,
            description=description,
            catalog_digest=(release_key[0] * 64),
            coverage_state=coverage_state,
            is_current=True,
            approved_at=(
                timezone.now()
                if coverage_state == ProductRelease.CoverageState.AUTHORITATIVE
                else None
            ),
        )
        for product_unit_code in product_unit_codes:
            ProductUnit.objects.create(
                product_release=release,
                product_unit_code=product_unit_code,
                source_value=product_unit_code,
                provenance="product-detail-test",
            )
        return release

    def detail(self, product_ident):
        return self.client.get(
            reverse(
                "product_detail",
                kwargs={"product_ident": product_ident},
            )
        )

    def test_product_coverage_percentage_uses_aggregate_counts(self):
        coverage = _aggregate_coverage(
            (
                {
                    "declared_expected": 2,
                    "expected": 2,
                    "accepted": 1,
                    "conflicts": 0,
                },
                {
                    "declared_expected": 3,
                    "expected": 3,
                    "accepted": 2,
                    "conflicts": 1,
                },
            ),
            True,
        )

        self.assertEqual(
            coverage,
            {
                "declared_expected": 5,
                "expected": 5,
                "accepted": 3,
                "conflicts": 1,
                "remaining": 2,
                "completion_percentage": 60.0,
            },
        )

    def test_product_coverage_is_unavailable_for_non_authoritative_stream(self):
        coverage = _aggregate_coverage(
            (
                {"declared_expected": 2, "expected": 2, "accepted": 1},
                {
                    "declared_expected": None,
                    "expected": None,
                    "accepted": None,
                },
            ),
            True,
        )

        self.assertTrue(all(value is None for value in coverage.values()))

    def test_product_coverage_is_unavailable_without_report_access(self):
        coverage = _aggregate_coverage(
            (
                {
                    "declared_expected": 2,
                    "expected": 2,
                    "accepted": 1,
                    "conflicts": 0,
                },
            ),
            False,
        )

        self.assertTrue(all(value is None for value in coverage.values()))

    def test_product_catalog_row_links_to_the_product_detail(self):
        self.client.force_login(self.default_user)

        response = self.client.get(reverse("products"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Managed Urban Atlas")
        self.assertContains(
            response,
            'href="{}"'.format(
                reverse(
                    "product_detail",
                    kwargs={"product_ident": PRODUCT_IDENT},
                )
            ),
        )

    def test_product_catalog_masks_coverage_without_report_access(self):
        self.client.force_login(self.default_user)

        response = self.client.get(reverse("products"))

        self.assertEqual(response.status_code, 200)
        products = response.context["product_catalog"]
        self.assertEqual(len(products), 2)
        for product in products:
            with self.subTest(product=product["ident"]):
                self.assertFalse(product["can_view_coverage"])
                self.assertIsNone(product["declared_expected"])
                self.assertIsNone(product["expected"])
                self.assertIsNone(product["accepted"])
                self.assertIsNone(product["completion_percentage"])
                self.assertEqual(product["plan_status"], "restricted")
        self.assertEqual(response.context["product_count"], 2)
        self.assertEqual(
            response.context["plan_filters"],
            ({"value": "restricted", "label": "Restricted", "count": 2},),
        )
        self.assertContains(response, "Coverage restricted")

    def test_default_user_sees_metadata_without_aggregate_coverage(self):
        self.client.force_login(self.default_user)

        response = self.detail(PRODUCT_IDENT)

        self.assertEqual(response.status_code, 200)
        product = response.context["product"]
        self.assertEqual(product.name, "Managed Urban Atlas")
        self.assertEqual(len(product.releases), 1)
        self.assertIsNone(product.releases[0].coverage)
        self.assertIsNone(product.releases[0].remaining_units)
        self.assertNotContains(response, "cz001l")
        self.assertNotContains(response, "cz002l")

    def test_product_manager_sees_aggregate_only_for_exact_grant(self):
        manager = get_user_model().objects.create_user(
            username="exact-product-manager",
            password="test-password",
        )
        manager.groups.add(
            Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        )
        UserProductGrant.objects.create(
            user=manager,
            product_ident=PRODUCT_IDENT,
        )
        self.client.force_login(manager)

        granted_response = self.detail(PRODUCT_IDENT)
        unrelated_response = self.detail(OTHER_PRODUCT_IDENT)

        granted_product = granted_response.context["product"]
        granted_release = granted_product.releases[0]
        granted_coverage = granted_release.coverage
        self.assertEqual(
            (
                granted_coverage.state,
                granted_coverage.expected,
                granted_coverage.accepted,
                granted_coverage.conflicts,
                granted_coverage.remaining,
                granted_coverage.completion_percentage,
            ),
            (
                ProductRelease.CoverageState.AUTHORITATIVE,
                2,
                0,
                0,
                2,
                0.0,
            ),
        )
        self.assertEqual(
            granted_release.remaining_units,
            ("cz001l", "cz002l"),
        )
        self.assertEqual(unrelated_response.status_code, 403)
        self.assertNotContains(unrelated_response, "de001l", status_code=403)

        catalog_response = self.client.get(reverse("products"))
        statuses = {
            product["ident"]: product["plan_status"]
            for product in catalog_response.context["product_catalog"]
        }
        self.assertEqual(
            statuses,
            {PRODUCT_IDENT: "approved"},
        )
        self.assertEqual(
            catalog_response.context["plan_filters"],
            (
                {"value": "approved", "label": "Approved", "count": 1},
            ),
        )

    def test_administrator_sees_aggregate_coverage_for_any_product(self):
        administrator = get_user_model().objects.create_user(
            username="product-detail-administrator",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

        response = self.detail(OTHER_PRODUCT_IDENT)

        product = response.context["product"]
        release = product.releases[0]
        self.assertEqual(release.coverage.expected, 1)
        self.assertEqual(release.coverage.remaining, 1)
        self.assertEqual(release.remaining_units, ("de001l",))

    def test_every_current_release_stream_has_separate_coverage(self):
        second = self.create_release(
            self.product,
            release_key="urban_atlas_secondary",
            description="Secondary delivery scope",
            product_unit_codes=("fr001l",),
        )
        administrator = get_user_model().objects.create_user(
            username="multi-release-administrator",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

        response = self.detail(PRODUCT_IDENT)

        self.assertEqual(response.status_code, 200)
        releases = response.context["product"].releases
        self.assertEqual(
            tuple(item.release.key for item in releases),
            (self.release.release_key, second.release_key),
        )
        self.assertEqual(
            tuple(item.coverage.expected for item in releases),
            (2, 1),
        )
        self.assertContains(response, self.release.release_key)
        self.assertContains(response, second.release_key)
        self.assertContains(response, "fr001l")

    def test_product_catalog_aggregates_multiple_current_release_streams(self):
        self.create_release(
            self.product,
            release_key="urban_atlas_secondary",
            description="Secondary delivery scope",
            product_unit_codes=("fr001l",),
        )
        administrator = get_user_model().objects.create_user(
            username="product-catalog-administrator",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

        response = self.client.get(reverse("products"))

        products = response.context["product_catalog"]
        urban_atlas = next(
            product
            for product in products
            if product["ident"] == PRODUCT_IDENT
        )
        self.assertEqual(urban_atlas["release_count"], 2)
        self.assertEqual(urban_atlas["declared_expected"], 3)
        self.assertEqual(urban_atlas["expected"], 3)
        self.assertEqual(urban_atlas["accepted"], 0)
        self.assertEqual(urban_atlas["completion_percentage"], 0.0)
        self.assertEqual(urban_atlas["plan_status"], "approved")
        self.assertEqual(len(products), 2)
        self.assertContains(response, 'id="tbl-products"')

    def test_draft_scope_contributes_to_total_but_not_completion(self):
        self.create_release(
            self.product,
            release_key="urban_atlas_draft",
            description="Draft delivery scope",
            product_unit_codes=("fr001l", "fr002l", "fr003l"),
            coverage_state=ProductRelease.CoverageState.DRAFT,
        )
        self.login_administrator()

        response = self.client.get(reverse("products"))

        product = self.catalog_product(response)
        self.assertEqual(product["declared_expected"], 5)
        self.assertTrue(product["scope_is_draft"])
        for field in ("expected", "accepted", "remaining", "completion_percentage"):
            self.assertIsNone(product[field])
        self.assertEqual(product["plan_status"], "mixed")
        self.assertContains(response, "Mixed plans")
        self.assertContains(response, "Review release plans")
        self.assertContains(response, "Includes unapproved scope")

        detail = self.detail(PRODUCT_IDENT)
        draft = next(
            release for release in detail.context["product"].releases
            if release.release.coverage_state == ProductRelease.CoverageState.DRAFT
        )
        self.assertEqual(draft.coverage.declared_expected, 3)
        self.assertIsNone(draft.coverage.completion_percentage)
        self.assertIsNone(draft.remaining_units)
        self.assertContains(detail, "Draft product units")
        self.assertContains(detail, "The declared scope is a draft.")

    def test_unknown_stream_prevents_partial_product_scope_total(self):
        self.create_release(
            self.product,
            release_key="urban_atlas_unknown",
            description="Unspecified delivery scope",
            coverage_state=ProductRelease.CoverageState.UNKNOWN,
        )
        self.login_administrator()

        response = self.client.get(reverse("products"))

        product = self.catalog_product(response)
        self.assertIsNone(product["declared_expected"])
        self.assertIsNone(product["expected"])
        self.assertIsNone(product["completion_percentage"])
        self.assertEqual(product["plan_status"], "mixed")
        self.assertEqual(product["expected_hint"], "Full scope unavailable")

    def test_draft_counts_are_hidden_without_report_access(self):
        self.create_release(
            self.product,
            release_key="urban_atlas_draft",
            description="Draft delivery scope",
            product_unit_codes=("fr001l",),
            coverage_state=ProductRelease.CoverageState.DRAFT,
        )
        self.client.force_login(self.default_user)

        response = self.client.get(reverse("products"))
        detail = self.detail(PRODUCT_IDENT)

        product = self.catalog_product(response)
        self.assertIsNone(product["declared_expected"])
        self.assertTrue(all(
            release["declared_expected"] is None
            for release in product["releases"]
        ))
        self.assertFalse(product["scope_is_draft"])
        self.assertNotContains(response, "Draft scope")
        self.assertTrue(all(
            release.coverage is None
            for release in detail.context["product"].releases
        ))
        self.assertNotContains(detail, "Draft product units")

    @patch(
        "qc_tool.common.load_product_definition",
        side_effect=AssertionError("Managed pages must use stored definitions"),
    )
    @patch(
        "qc_tool.frontend.dashboard.views.products."
        "available_product_descriptions",
        side_effect=AssertionError("Managed catalog must use stored products"),
    )
    def test_managed_pages_use_database_snapshots_without_definition_files(
        self, descriptions, definition_loader,
    ):
        definition = QcDefinition.objects.create(
            product_ident=PRODUCT_IDENT,
            digest="d" * 64,
            description="Stored definition",
            document={"steps": [{"required": True}, {"required": False}]},
            source_path="unavailable/product.json",
        )
        ProductReleaseDefinition.objects.create(
            product_release=self.release,
            qc_definition=definition,
            is_primary=True,
        )
        self.login_administrator()

        response = self.client.get(reverse("products"))
        detail = self.detail(PRODUCT_IDENT)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        checks = detail.context["product"].releases[0].quality_checks
        self.assertEqual((checks.total, checks.required, checks.optional), (2, 1, 1))
        descriptions.assert_not_called()
        definition_loader.assert_not_called()

    def login_administrator(self):
        administrator = get_user_model().objects.create_user(
            username="catalog-scope-administrator",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

    def catalog_product(self, response):
        return next(
            product for product in response.context["product_catalog"]
            if product["ident"] == PRODUCT_IDENT
        )

    def test_release_streams_are_bounded_and_truncation_is_visible(self):
        for index in range(MAX_CURRENT_RELEASES):
            self.create_release(
                self.product,
                release_key="bounded-stream-{:02d}".format(index),
                description="Bounded stream {:02d}".format(index),
            )
        self.client.force_login(self.default_user)

        response = self.detail(PRODUCT_IDENT)

        product = response.context["product"]
        self.assertEqual(len(product.releases), MAX_CURRENT_RELEASES)
        self.assertTrue(product.releases_truncated)
        self.assertContains(response, "Additional release streams exist")
