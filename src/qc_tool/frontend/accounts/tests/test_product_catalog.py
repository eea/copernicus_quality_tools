from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase

from qc_tool.frontend.accounts.services import products
from qc_tool.frontend.dashboard.models import (
    Product,
    ProductRelease,
    ProductReleaseDefinition,
    QcDefinition,
)


class ManagedProductCatalogTests(TestCase):
    def definition(self, ident, *, description=None, digest="a"):
        return QcDefinition.objects.create(
            product_ident=ident,
            digest=digest * 64,
            description=description or f"Specification for {ident}",
            document={"description": description or ident, "steps": []},
            source_path=f"/unavailable/{ident}.json",
        )

    def release(self, ident, definition, *, current=True, active=True, state="draft"):
        product = Product.objects.create(ident=ident, name=f"Product {ident}", is_active=active)
        release = ProductRelease.objects.create(
            product=product,
            release_key=f"upload:{ident}",
            revision=1,
            description=product.name,
            catalog_digest="b" * 64,
            source_kind=ProductRelease.SourceKind.UPLOAD,
            coverage_state=state,
            is_current=current,
        )
        ProductReleaseDefinition.objects.create(
            product_release=release, qc_definition=definition, is_primary=True,
        )
        return release

    @patch("qc_tool.common.get_product_descriptions", return_value={"bundled": "Bundled recipe"})
    def test_empty_catalog_stays_empty_despite_bundled_recipes(self, discover):
        self.assertEqual(products.available_product_descriptions(), {})
        self.assertEqual(products.available_product_idents(), frozenset())
        self.assertEqual(products.product_ident_choices(), ())
        discover.assert_not_called()
        self.assertFalse(Product.objects.exists())
        self.assertFalse(QcDefinition.objects.exists())

    def test_current_managed_definition_is_available_without_source_file(self):
        definition = self.definition("uploaded_recipe", description="Stored uploaded specification")
        self.release("uploaded_product", definition)

        self.assertEqual(products.available_product_descriptions(), {
            "uploaded_recipe": "Stored uploaded specification",
        })
        self.assertEqual(products.grantable_product_descriptions(), {
            "uploaded_recipe": "Stored uploaded specification",
            "uploaded_product": "Product uploaded_product",
        })

    def test_unlinked_historical_archived_and_retired_definitions_are_unavailable(self):
        self.definition("unlinked")
        self.release("historical", self.definition("historical_recipe"), current=False)
        self.release("archived", self.definition("archived_recipe"), active=False)
        self.release("retired", self.definition("retired_recipe"), state="retired")
        Product.objects.create(ident="unconfigured", name="Unconfigured product")

        self.assertEqual(products.available_product_descriptions(), {})
        self.assertEqual(products.grantable_product_descriptions(), {})
        self.assertEqual(dict(products.product_ident_choices(include=("archived",))), {
            "archived": "archived — unavailable legacy product",
        })

    def test_historical_definition_revision_does_not_replace_current_description(self):
        current = self.definition("recipe", description="Current specification")
        self.release("managed", current)
        self.definition("recipe", description="Unlinked newer specification", digest="c")

        self.assertEqual(products.available_product_descriptions(), {"recipe": "Current specification"})

    @patch.object(products, "_available_definition_links", side_effect=DatabaseError("offline"))
    def test_database_failure_remains_typed_without_file_fallback(self, _links):
        with self.assertRaises(products.ProductCatalogUnavailable):
            products.available_product_descriptions()
        with self.assertRaises(products.ProductCatalogUnavailable):
            products.product_ident_choices()
