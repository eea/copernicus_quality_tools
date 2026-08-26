"""Public contracts for the Products workspace hierarchy and detail page."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.urls import resolve
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.services.products.lookup import (
    MAX_CURRENT_RELEASES,
)
from qc_tool.frontend.dashboard.views.products.data import (
    get_product_definition,
)


PRODUCT_IDENT = "clms_ua_lcuc_c2021-2024_v010ha"
OTHER_PRODUCT_IDENT = "clms_test_other_product"


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
class DefinitionBackedProductDetailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="definition-product-reader",
            password="test-password",
        )
        self.client.force_login(self.user)

    @patch(
        "qc_tool.frontend.dashboard.services.products.detail."
        "load_product_definition",
        return_value={
            "description": "Urban Atlas Change 2021-2024",
            "steps": [
                {"check_ident": "required.check", "required": True},
                {"check_ident": "optional.check", "required": False},
            ],
        },
    )
    @patch(
        "qc_tool.frontend.dashboard.services.products.detail."
        "available_product_descriptions",
        return_value={PRODUCT_IDENT: "Urban Atlas Change 2021-2024"},
    )
    def test_known_definition_backed_product_renders_safe_metadata(
        self,
        _descriptions,
        _definition,
    ):
        response = self.client.get(
            reverse(
                "product_detail",
                kwargs={"product_ident": PRODUCT_IDENT},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/products/detail.html")
        product = response.context["product"]
        self.assertEqual(product.ident, PRODUCT_IDENT)
        self.assertEqual(product.name, "Urban Atlas Change 2021-2024")
        self.assertFalse(product.managed)
        self.assertEqual(
            (
                product.quality_checks.total,
                product.quality_checks.required,
                product.quality_checks.optional,
            ),
            (2, 1, 1),
        )
        self.assertEqual(product.releases, ())
        self.assertContains(response, PRODUCT_IDENT)
        self.assertContains(response, "Urban Atlas Change 2021-2024")

    @patch(
        "qc_tool.frontend.dashboard.services.products.detail."
        "available_product_descriptions",
        return_value={PRODUCT_IDENT: "Urban Atlas Change 2021-2024"},
    )
    def test_unknown_and_noncanonical_product_identifiers_return_404(
        self,
        descriptions,
    ):
        unknown = self.client.get(
            reverse(
                "product_detail",
                kwargs={"product_ident": "unknown_product"},
            )
        )
        malformed = self.client.get(
            reverse(
                "product_detail",
                kwargs={"product_ident": PRODUCT_IDENT.upper()},
            )
        )

        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(malformed.status_code, 404)
        self.assertEqual(descriptions.call_count, 1)

    @patch(
        "qc_tool.frontend.dashboard.services.products.detail."
        "load_product_definition",
        side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
    )
    @patch(
        "qc_tool.frontend.dashboard.services.products.detail."
        "available_product_descriptions",
        return_value={PRODUCT_IDENT: "Urban Atlas Change 2021-2024"},
    )
    def test_invalid_definition_encoding_keeps_metadata_page_available(
        self,
        _descriptions,
        _definition,
    ):
        response = self.client.get(
            reverse("product_detail", args=(PRODUCT_IDENT,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["product"].quality_checks)
        self.assertContains(response, "Check totals are unavailable")

    def test_definition_data_route_normalizes_legacy_uppercase_identifiers(self):
        with TemporaryDirectory() as directory:
            definition_path = Path(directory, "product.json")
            definition_path.write_text("{}", encoding="utf-8")
            with patch(
                "qc_tool.frontend.dashboard.views.products.data."
                "locate_product_definition",
                return_value=definition_path,
            ) as locate_definition:
                response = get_product_definition(
                    RequestFactory().get(
                        reverse("product_definition_json", args=("PRODUCT",))
                    ),
                    "PRODUCT",
                )

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
        self.product, self.release = self.create_product_release(
            PRODUCT_IDENT,
            name="Managed Urban Atlas",
            aoi_codes=("cz001l", "cz002l"),
        )
        self.other_product, self.other_release = self.create_product_release(
            OTHER_PRODUCT_IDENT,
            name="Other managed product",
            aoi_codes=("de001l",),
        )

    def create_product_release(self, product_ident, *, name, aoi_codes):
        product = Product.objects.create(
            ident=product_ident,
            name=name,
            description="{} description".format(name),
        )
        release = self.create_release(
            product,
            release_key="{}_release".format(product_ident),
            description="{} release".format(name),
            aoi_codes=aoi_codes,
        )
        return product, release

    def create_release(
        self,
        product,
        *,
        release_key,
        description,
        aoi_codes=(),
    ):
        release = ProductRelease.objects.create(
            product=product,
            release_key=release_key,
            revision=1,
            description=description,
            catalog_digest=(release_key[0] * 64),
            coverage_state=ProductRelease.CoverageState.AUTHORITATIVE,
            is_current=True,
            approved_at=timezone.now(),
        )
        for aoi_code in aoi_codes:
            ProductAOI.objects.create(
                product_release=release,
                aoi_code=aoi_code,
                source_value=aoi_code,
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

    def test_product_catalog_card_links_to_the_product_detail(self):
        self.client.force_login(self.default_user)

        response = self.client.get(reverse("products"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'href="{}"'.format(
                reverse(
                    "product_detail",
                    kwargs={"product_ident": PRODUCT_IDENT},
                )
            ),
        )

    def test_default_user_sees_metadata_without_aggregate_coverage(self):
        self.client.force_login(self.default_user)

        response = self.detail(PRODUCT_IDENT)

        self.assertEqual(response.status_code, 200)
        product = response.context["product"]
        self.assertEqual(product.name, "Managed Urban Atlas")
        self.assertEqual(len(product.releases), 1)
        self.assertIsNone(product.releases[0].coverage)
        self.assertIsNone(product.releases[0].remaining_aois)
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
                granted_coverage.submitted,
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
            granted_release.remaining_aois,
            ("cz001l", "cz002l"),
        )
        unrelated_product = unrelated_response.context["product"]
        unrelated_release = unrelated_product.releases[0]
        self.assertIsNone(unrelated_release.coverage)
        self.assertIsNone(unrelated_release.remaining_aois)
        self.assertNotContains(unrelated_response, "de001l")

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
        self.assertEqual(release.remaining_aois, ("de001l",))

    def test_every_current_release_stream_has_separate_coverage(self):
        second = self.create_release(
            self.product,
            release_key="urban_atlas_secondary",
            description="Secondary delivery scope",
            aoi_codes=("fr001l",),
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

    def test_product_catalog_groups_multiple_release_streams_into_one_card(self):
        self.create_release(
            self.product,
            release_key="urban_atlas_secondary",
            description="Secondary delivery scope",
        )
        self.client.force_login(self.default_user)

        response = self.client.get(reverse("products"))

        products = response.context["product_catalog"]
        urban_atlas = next(
            product
            for product in products
            if product["ident"] == PRODUCT_IDENT
        )
        self.assertEqual(urban_atlas["release_count"], 2)
        self.assertEqual(len(products), 2)
        self.assertContains(response, "2 current release streams")

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
