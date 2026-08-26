"""Explicit immutable product-catalog manifest tests."""

import json
from dataclasses import replace
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.test import TestCase
from django.template.loader import render_to_string

from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import QcDefinition
from qc_tool.frontend.dashboard.services.catalog import CatalogError
from qc_tool.frontend.dashboard.services.catalog import load_catalog_manifest
from qc_tool.frontend.dashboard.services.catalog import list_current_product_coverage
from qc_tool.frontend.dashboard.services.catalog import synchronize_product_catalog


class ProductCatalogSynchronizationTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.definition_path = self.root / "test_definition.json"
        self.definition_path.write_text(
            json.dumps(
                {
                    "description": "Test executable definition",
                    "steps": [
                        {
                            "check_ident": "qc_tool.vector.naming",
                            "required": True,
                            "parameters": {
                                "aoi_codes": ["EE001L1", "ee002l", "ee001l"]
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def write_manifest(self, *, revision=1, state="authoritative"):
        path = self.root / "catalog.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "products": [
                        {
                            "ident": "TEST_DEFINITION",
                            "name": "Test product",
                            "description": "Catalog-owned product",
                            "releases": [
                                {
                                    "release_key": "test-2026",
                                    "revision": revision,
                                    "description": "Test 2026",
                                    "definition_idents": ["test_definition"],
                                    "primary_definition": "test_definition",
                                    "coverage": {
                                        "state": state,
                                        "source_definition": "test_definition",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def load(self, path):
        with patch(
            "qc_tool.frontend.dashboard.services.catalog.manifest."
            "locate_product_definition",
            return_value=self.definition_path,
        ):
            return load_catalog_manifest(path)

    def test_manifest_normalizes_and_deduplicates_expected_aois(self):
        snapshot = self.load(self.write_manifest())

        release = snapshot.releases[0]
        self.assertEqual(release.product_ident, "test_definition")
        self.assertEqual(release.aoi_codes, ("ee001l", "ee002l"))
        self.assertEqual(release.aoi_provenance, "definition")

    def test_sync_is_idempotent_and_creates_immutable_rows(self):
        snapshot = self.load(self.write_manifest())

        first = synchronize_product_catalog(snapshot)
        second = synchronize_product_catalog(snapshot)

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(QcDefinition.objects.count(), 1)
        self.assertEqual(ProductRelease.objects.count(), 1)
        self.assertEqual(
            list(ProductAOI.objects.values_list("aoi_code", flat=True)),
            ["ee001l", "ee002l"],
        )

    def test_products_page_rows_expose_authoritative_completion(self):
        synchronize_product_catalog(self.load(self.write_manifest()))

        with self.assertNumQueries(1):
            rows = list_current_product_coverage()
        rendered = render_to_string(
            "dashboard/products/index.html",
            {
                "product_catalog": rows,
                "product_catalog_available": True,
                "catalog_managed": True,
            },
        )

        self.assertEqual(rows[0]["expected"], 2)
        self.assertEqual(rows[0]["submitted"], 0)
        self.assertIn("0 / 2 AOIs accepted", rendered)

    def test_changed_content_requires_a_higher_release_revision(self):
        first = self.load(self.write_manifest(revision=1))
        synchronize_product_catalog(first)
        definition = json.loads(self.definition_path.read_text(encoding="utf-8"))
        definition["steps"][0]["parameters"]["aoi_codes"].append("ee003l")
        self.definition_path.write_text(json.dumps(definition), encoding="utf-8")
        changed_same_revision = self.load(self.write_manifest(revision=1))

        with self.assertRaises(CatalogError) as raised:
            synchronize_product_catalog(changed_same_revision)
        self.assertEqual(raised.exception.code, "immutable_release_changed")
        self.assertEqual(ProductRelease.objects.count(), 1)

        changed_next_revision = self.load(self.write_manifest(revision=2))
        synchronize_product_catalog(changed_next_revision)
        current = ProductRelease.objects.get(is_current=True)
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.supersedes.revision, 1)
        self.assertEqual(ProductRelease.objects.count(), 2)

    def test_dry_run_reports_changes_without_writing(self):
        result = synchronize_product_catalog(
            self.load(self.write_manifest()),
            dry_run=True,
        )

        self.assertTrue(result.changed)
        self.assertFalse(Product.objects.exists())

    def test_product_display_metadata_update_is_reported_as_a_change(self):
        snapshot = self.load(self.write_manifest())
        synchronize_product_catalog(snapshot)
        updated_snapshot = replace(
            snapshot,
            releases=(
                replace(
                    snapshot.releases[0],
                    product_name="Renamed test product",
                ),
            ),
        )

        result = synchronize_product_catalog(updated_snapshot, dry_run=True)

        self.assertTrue(result.changed)
        self.assertEqual(result.products_updated, 1)
        self.assertEqual(
            Product.objects.get().name,
            "Test product",
        )

    def test_wildcard_definition_cannot_be_authoritative_denominator(self):
        definition = json.loads(self.definition_path.read_text(encoding="utf-8"))
        definition["steps"][0]["parameters"]["aoi_codes"] = ["*", "ee001l"]
        self.definition_path.write_text(json.dumps(definition), encoding="utf-8")

        with self.assertRaises(CatalogError) as raised:
            self.load(self.write_manifest())
        self.assertEqual(raised.exception.code, "invalid_manifest")
