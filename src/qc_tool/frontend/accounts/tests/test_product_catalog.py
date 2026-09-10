import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from qc_tool.frontend.accounts.services import products


def json_error():
    return json.JSONDecodeError("invalid definition", "", 0)


class ProductCatalogFallbackTests(SimpleTestCase):
    def scan(self, product_dirs):
        with patch.object(
            products,
            "product_definition_directories",
            return_value=product_dirs,
        ), patch.object(
            products,
            "get_product_descriptions",
            side_effect=json_error(),
        ):
            return products.available_product_descriptions()

    def test_invalid_definition_does_not_hide_valid_definition(self):
        with TemporaryDirectory() as temporary_dir:
            product_dir = Path(temporary_dir)
            valid_path = product_dir / "valid_product.json"
            invalid_path = product_dir / "invalid_product.json"
            valid_path.write_text('{"description": "Valid product"}')
            invalid_path.write_text("<<<<<<< unresolved merge marker")

            with self.assertLogs(products.__name__, level="WARNING") as logs:
                descriptions = self.scan([product_dir])

        self.assertEqual(descriptions["valid_product"], "Valid product")
        self.assertEqual(
            descriptions["invalid_product"],
            products.INVALID_PRODUCT_DESCRIPTION,
        )
        self.assertIn(str(invalid_path), logs.output[0])
        self.assertIn("Expecting value", logs.output[0])

    def test_earlier_configured_directory_overrides_later_directory(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_dir = Path(first)
            second_dir = Path(second)
            (first_dir / "shared.json").write_text(
                '{"description": "First directory"}'
            )
            (second_dir / "shared.json").write_text(
                '{"description": "Second directory"}'
            )

            descriptions = self.scan([first_dir, second_dir])

        self.assertEqual(descriptions["shared"], "First directory")

    def test_every_matching_stem_is_included_even_with_schema_errors(self):
        with TemporaryDirectory() as temporary_dir:
            product_dir = Path(temporary_dir)
            (product_dir / "valid.json").write_text(
                '{"description": "Valid"}'
            )
            (product_dir / "missing_description.json").write_text("{}")
            (product_dir / "not_an_object.json").write_text("[]")
            (product_dir / "ignored.txt").write_text("not a definition")

            with self.assertLogs(products.__name__, level="WARNING"):
                descriptions = self.scan([product_dir])

        self.assertEqual(
            set(descriptions),
            {"valid", "missing_description", "not_an_object"},
        )
        self.assertEqual(
            descriptions["missing_description"],
            products.INVALID_PRODUCT_DESCRIPTION,
        )
        self.assertEqual(
            descriptions["not_an_object"],
            products.INVALID_PRODUCT_DESCRIPTION,
        )

    def test_invalid_description_type_from_shared_loader_triggers_scan(self):
        with TemporaryDirectory() as temporary_dir:
            product_dir = Path(temporary_dir)
            (product_dir / "invalid_description.json").write_text(
                '{"description": []}'
            )

            with patch.object(
                products,
                "product_definition_directories",
                return_value=[product_dir],
            ), patch.object(
                products,
                "get_product_descriptions",
                return_value={"invalid_description": []},
            ), self.assertLogs(products.__name__, level="WARNING"):
                descriptions = products.available_product_descriptions()

        self.assertEqual(
            descriptions["invalid_description"],
            products.INVALID_PRODUCT_DESCRIPTION,
        )

    def test_fatal_directory_failure_remains_typed(self):
        with TemporaryDirectory() as temporary_dir:
            missing_dir = Path(temporary_dir) / "missing"

            with self.assertRaises(products.ProductCatalogUnavailable):
                self.scan([missing_dir])

    def test_healthy_shared_loader_remains_the_primary_path(self):
        expected = {"clc2024": "CLC"}
        with patch.object(
            products,
            "get_product_descriptions",
            return_value=expected,
        ), patch.object(products, "_scan_product_descriptions") as fallback:
            descriptions = products.available_product_descriptions()

        self.assertIs(descriptions, expected)
        fallback.assert_not_called()
