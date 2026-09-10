"""Directory imports preserve curated scope and historical definition content."""

import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import QcDefinition
from qc_tool.frontend.dashboard.services.catalog import CatalogError
from qc_tool.frontend.dashboard.services.catalog import list_current_product_coverage
from qc_tool.frontend.dashboard.services.catalog import synchronize_product_catalog
from qc_tool.frontend.dashboard.services.catalog.contracts import CatalogSnapshot
from qc_tool.frontend.dashboard.services.catalog.definition_directory import (
    read_definition_directories,
)
from qc_tool.frontend.dashboard.services.catalog.definition_import import (
    synchronize_definition_directories,
)
from qc_tool.frontend.dashboard.services.catalog.manifest.release_parser import (
    parse_release_document,
)
from qc_tool.frontend.dashboard.services.catalog.revisions import store_definition


class DefinitionDirectoryImportTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write_definition()

    def write_definition(self, ident="example", *, codes=None, document=None):
        if document is None:
            document = {
                "description": "Example product",
                "steps": [{
                    "check_ident": "qc_tool.vector.naming",
                    "required": True,
                    "parameters": {
                        "reference_year": "2024",
                        "aoi_codes": codes if codes is not None else ["CZ", "cz", "SK"],
                    },
                }],
            }
        path = self.root / (ident + ".json")
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def sync(self, *, dry_run=False):
        return synchronize_definition_directories([self.root], dry_run=dry_run)

    def test_import_stores_queryable_json_and_canonical_draft_aoi_scope(self):
        result = self.sync()
        self.assertEqual(result.catalog.definitions_created, 1)
        self.assertEqual(result.catalog.products_created, 1)
        self.assertEqual(result.catalog.aois_created, 2)
        definition = QcDefinition.objects.get(
            document__steps__0__parameters__reference_year="2024",
        )
        self.assertEqual(definition.document["steps"][0]["parameters"]["aoi_codes"], ["CZ", "cz", "SK"])
        release = ProductRelease.objects.get()
        self.assertEqual(release.source_kind, "definition")
        self.assertEqual(release.coverage_state, "draft")
        self.assertIsNone(release.approved_at)
        self.assertEqual(list(release.aois.values_list("aoi_code", flat=True)), ["cz", "sk"])
        report = list_current_product_coverage()[0]
        self.assertEqual(report["declared_expected"], 2)
        self.assertIsNone(report["expected"])
        self.assertIsNone(report["completion_percentage"])

    def test_repeated_import_and_relocated_files_are_idempotent(self):
        self.sync()
        original_path = QcDefinition.objects.get().source_path
        relocated = self.root / "relocated"
        relocated.mkdir()
        (relocated / "example.json").write_bytes((self.root / "example.json").read_bytes())
        self.assertFalse(self.sync().changed)
        self.assertFalse(synchronize_definition_directories([relocated]).changed)
        self.assertEqual(QcDefinition.objects.get().source_path, original_path)
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_changed_file_creates_successor_and_preserves_old_scope(self):
        self.sync()
        previous = ProductRelease.objects.get()
        old_definition = QcDefinition.objects.get()
        self.write_definition(codes=["CZ", "AT"])
        result = self.sync()
        current = ProductRelease.objects.get(is_current=True)
        self.assertEqual(result.catalog.definitions_created, 1)
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.supersedes_id, previous.pk)
        self.assertEqual(list(previous.aois.values_list("aoi_code", flat=True)), ["cz", "sk"])
        old_definition.refresh_from_db()
        self.assertEqual(old_definition.document["steps"][0]["parameters"]["aoi_codes"], ["CZ", "cz", "SK"])
        self.assertFalse(self.sync().changed)

    def test_whitespace_changes_preserve_raw_byte_digest_identity(self):
        self.sync()
        old = QcDefinition.objects.get()
        path = self.root / "example.json"
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        self.sync()
        current = ProductRelease.objects.get(is_current=True)
        new = current.definition_links.get().qc_definition
        self.assertEqual(old.document, new.document)
        self.assertNotEqual(old.digest, new.digest)
        self.assertEqual(current.revision, 2)

    def test_scientific_notation_round_trip_does_not_create_false_collision(self):
        self.write_definition(document={
            "description": "Scientific nodata value",
            "steps": [{
                "check_ident": "qc_tool.raster.value",
                "required": False,
                "parameters": {"nodata_value": -3.4028235e38},
            }],
        })
        self.sync()
        self.assertFalse(self.sync().changed)
        self.assertEqual(QcDefinition.objects.count(), 1)

    def test_same_digest_cannot_conceal_changed_boolean_content(self):
        self.sync()
        definition = QcDefinition.objects.get()
        tampered = definition.document
        tampered["steps"][0]["required"] = 1
        QcDefinition.objects.filter(pk=definition.pk).update(document=tampered)
        with self.assertRaises(CatalogError) as raised:
            self.sync()
        self.assertEqual(raised.exception.code, "definition_digest_collision")

    def test_missing_empty_and_wildcard_lists_do_not_invent_expected_deliveries(self):
        for ident, parameters in (
            ("missing", {}),
            ("empty", {"aoi_codes": []}),
            ("wildcard", {"aoi_codes": ["*"]}),
        ):
            self.write_definition(ident, document={
                "description": ident,
                "steps": [{"check_ident": "qc_tool.raster.naming", "parameters": parameters}],
            })
        result = self.sync()
        self.assertEqual(result.unknown_scopes, 3)
        for release in ProductRelease.objects.exclude(product__ident="example"):
            self.assertEqual(release.coverage_state, "unknown")
            self.assertFalse(release.aois.exists())

    def test_integer_required_flags_are_preserved(self):
        self.write_definition(document={
            "description": "Integer flags",
            "steps": [
                {"check_ident": "qc_tool.raster.unzip", "required": 1},
                {"check_ident": "qc_tool.raster.epsg", "required": 0},
            ],
        })
        self.sync()
        self.assertIs(type(QcDefinition.objects.get().document["steps"][0]["required"]), int)
        from qc_tool.frontend.dashboard.services.products.presentation import _quality_checks

        summary = _quality_checks(QcDefinition.objects.get().document)
        self.assertEqual((summary.required, summary.optional), (1, 1))

    def test_invalid_definition_stops_entire_import(self):
        bad = self.root / "z_bad.json"
        for payload in (
            "not json",
            '{"description":"bad","steps":[{}]}',
            '{"description":"bad","steps":[{"check_ident":"qc_tool.vector.naming","parameters":[]}]}',
            '{"description":"bad","steps":[],"value":NaN}',
            '{"description":"bad","steps":[],"value":1e400}',
            '{"description":"bad","description":"duplicate","steps":[]}',
        ):
            with self.subTest(payload=payload):
                bad.write_text(payload, encoding="utf-8")
                with self.assertRaises(CatalogError):
                    self.sync()
                self.assertFalse(QcDefinition.objects.exists())
                self.assertFalse(Product.objects.exists())

    def test_ambiguous_filenames_and_empty_sources_fail_explicitly(self):
        duplicate = self.root / "duplicate"
        duplicate.mkdir()
        (duplicate / "EXAMPLE.json").write_bytes((self.root / "example.json").read_bytes())
        with self.assertRaises(CatalogError) as raised:
            synchronize_definition_directories([self.root, duplicate])
        self.assertEqual(raised.exception.code, "duplicate_definition_ident")
        for path in self.root.glob("*.json"):
            path.unlink()
        with self.assertRaises(CatalogError) as raised:
            self.sync()
        self.assertEqual(raised.exception.code, "empty_definition_directory")

    def test_disagreeing_or_invalid_aoi_lists_are_rejected(self):
        path = self.root / "example.json"
        doc = json.loads(path.read_text())
        doc["steps"].append({
            "check_ident": "qc_tool.vector.naming_pdf",
            "parameters": {"aoi_codes": ["AT"]},
        })
        self.write_definition(document=doc)
        with self.assertRaises(CatalogError):
            self.sync()
        self.write_definition(codes=["invalid\u0000code"])
        with self.assertRaises(CatalogError):
            self.sync()
        self.assertFalse(QcDefinition.objects.exists())

    def test_late_persistence_failure_rolls_back_earlier_definitions(self):
        self.write_definition("second")
        real_store = store_definition

        def failing_store(snapshot):
            if snapshot.product_ident == "second":
                raise CatalogError("injected_failure", "Failure after first release")
            return real_store(snapshot)

        with patch(
            "qc_tool.frontend.dashboard.services.catalog.definition_import.store_definition",
            side_effect=failing_store,
        ), self.assertRaises(CatalogError):
            self.sync()
        self.assertFalse(QcDefinition.objects.exists())
        self.assertFalse(Product.objects.exists())
        self.assertFalse(ProductAOI.objects.exists())

    def test_dry_run_and_check_do_not_persist_records(self):
        self.assertTrue(self.sync(dry_run=True).changed)
        self.assertFalse(Product.objects.exists())
        with self.assertRaises(CommandError):
            call_command("sync_product_definitions", str(self.root), check=True, stdout=StringIO())
        self.assertFalse(QcDefinition.objects.exists())
        call_command("sync_product_definitions", str(self.root), stdout=StringIO())
        call_command("sync_product_definitions", str(self.root), check=True, stdout=StringIO())
        self.assertEqual(ProductRelease.objects.count(), 1)

    def test_removed_source_does_not_delete_historical_catalog(self):
        self.write_definition("second")
        self.sync()
        (self.root / "example.json").unlink()
        self.assertFalse(self.sync().changed)
        self.assertEqual(ProductRelease.objects.count(), 2)
        self.assertEqual(QcDefinition.objects.count(), 2)

    def test_manifest_takeover_preserves_curated_draft_and_authoritative_scope(self):
        self.sync()
        definition = read_definition_directories([self.root])[0]
        for revision, state in ((2, "draft"), (3, "authoritative")):
            with self.subTest(state=state):
                curated = parse_release_document(
                    {
                        "release_key": "definition:example",
                        "revision": revision,
                        "description": "Reviewed plan",
                        "definition_idents": ["example"],
                        "coverage": {"state": state, "aoi_codes": ["CZ"]},
                    },
                    product_ident="example",
                    product_name="Curated product name",
                    product_description="Reviewed product",
                    definition_loader=lambda _ident: definition,
                )
                synchronize_product_catalog(CatalogSnapshot(releases=(curated,)))
                self.write_definition(codes=["AT", "SK", str(revision)])
                result = self.sync()
                current = ProductRelease.objects.get(is_current=True)
                self.assertEqual(result.managed_definitions, 1)
                self.assertEqual(current.source_kind, "manifest")
                self.assertEqual(current.revision, revision)
                self.assertEqual(current.definition_links.get().qc_definition.digest, definition.digest)
                self.assertEqual(list(current.aois.values_list("aoi_code", flat=True)), ["cz"])
                self.assertEqual(current.product.name, "Curated product name")
                self.assertFalse(self.sync().changed)

    def test_grouped_manifest_does_not_create_duplicate_business_product(self):
        definition = read_definition_directories([self.root])[0]
        curated = parse_release_document(
            {
                "release_key": "business-2024",
                "revision": 1,
                "description": "Grouped business product",
                "definition_idents": ["example"],
                "coverage": {"state": "unknown"},
            },
            product_ident="business",
            product_name="Business product",
            product_description="",
            definition_loader=lambda _ident: definition,
        )
        synchronize_product_catalog(CatalogSnapshot(releases=(curated,)))
        self.assertEqual(self.sync().managed_definitions, 1)
        self.assertEqual(list(Product.objects.values_list("ident", flat=True)), ["business"])
