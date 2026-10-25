"""Version inventory reuses retained originals and existing catalog history."""

from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.models import (
    Product, ProductRelease, ProductReleaseDefinition, QcDefinition,
)
from qc_tool.frontend.dashboard.services.storage_admin import downloads, files, versions


class VersionFixture:
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-storage-versions-")))
        self.work = self.root / "work"
        self.uploaded = self.work / "product_definitions"
        self.boundaries = self.root / "boundaries"
        self.deployment = self.root / "deployed-specifications"
        for directory in (self.uploaded, self.boundaries, self.deployment):
            directory.mkdir(parents=True)
        self.enterContext(patch.dict(CONFIG, work_dir=self.work,
            boundary_dir=self.boundaries, product_dirs=[self.deployment]))
        self.enterContext(override_settings(
            MEDIA_ROOT=self.root / "incoming", QC_TOOL_STORAGE_ROOTS=[],
            QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfer", S3_CREDENTIALS_DIR=self.root / "credentials",
        ))

    def specification(self, ident="test-product", payload=b'{ "original": true }\n'):
        digest = sha256(payload).hexdigest()
        directory = self.uploaded / ".versions" / ident
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (digest + ".json")
        target.write_bytes(payload)
        return digest, target

    def marker(self, ident, state):
        directory = self.uploaded / ".state"
        directory.mkdir(exist_ok=True)
        path = directory / (ident + ".json")
        path.write_text(json.dumps(state))
        return path

    def generation(self, number, *, current=False, legacy=False):
        ident = ("legacy-" if legacy else "gen-") + f"{number:032x}"
        directory = self.boundaries / ".boundary-generations" / ident
        for kind in ("raster", "vector"):
            (directory / kind).mkdir(parents=True, exist_ok=True)
            (directory / kind / "original.txt").write_bytes(b"unchanged boundary bytes")
        if current:
            (self.boundaries / ".boundary-current").symlink_to(".boundary-generations/" + ident)
        return ident, directory

    def listing(self, kind="specifications", **options):
        return versions.list_versions(kind, include_catalog=False, **options)


class StorageVersionFilesTests(VersionFixture, SimpleTestCase):
    def test_current_and_previous_boundary_versions_open_their_exact_retained_folders(self):
        old, _ = self.generation(1, legacy=True)
        current, _ = self.generation(2, current=True)
        listing = self.listing("boundaries")
        self.assertEqual([row["version_id"] for row in listing["entries"]], [current, old])
        self.assertEqual([row["status"] for row in listing["entries"]], ["current", "previous"])
        for row in listing["entries"]:
            self.assertTrue(row["available"])
            self.assertEqual(row["selection_paths"], (row["path"],))
            opened = files.list_entries(row["area"], row["path"])
            self.assertEqual({entry["name"] for entry in opened["entries"]}, {"raster", "vector"})
        self.assertNotIn(str(self.root), str(listing))
        self.assertEqual(listing["warnings"], [])

    def test_unmanaged_boundaries_download_only_the_current_raster_and_vector_folders(self):
        for kind in ("raster", "vector"):
            (self.boundaries / kind).mkdir()
        self.generation(4)
        listing = self.listing("boundaries")
        current = listing["entries"][0]
        self.assertEqual((current["version_id"], current["status"]), ("legacy-unmanaged", "current"))
        self.assertEqual(current["selection_paths"], ("raster", "vector"))
        plan = downloads.prepare_zip(current["area"], current["selection_paths"])
        self.assertTrue(all(not entry.path.startswith(".boundary-generations") for entry in plan.entries))

    def test_corrupt_boundary_pointer_does_not_choose_a_previous_version(self):
        self.generation(1)
        (self.boundaries / ".boundary-current").symlink_to("../../private")
        listing = self.listing("boundaries")
        self.assertEqual(listing["entries"][0]["status"], "unknown")
        self.assertTrue(listing["warnings"])
        self.assertFalse(any(row["status"] == "current" for row in listing["entries"]))

    def test_missing_active_boundary_and_incomplete_history_are_explicit(self):
        old, directory = self.generation(1)
        (directory / "raster" / "original.txt").unlink()
        (directory / "raster").rmdir()
        missing = "gen-" + "f" * 32
        (self.boundaries / ".boundary-current").symlink_to(".boundary-generations/" + missing)
        listing = self.listing("boundaries")
        self.assertEqual({row["version_id"] for row in listing["entries"]}, {old, missing})
        self.assertTrue(all(not row["available"] and row["status"] == "unavailable" for row in listing["entries"]))
        self.assertTrue(listing["warnings"])

    def test_boundary_generation_symlinks_are_never_followed(self):
        private = self.root / "private"
        private.mkdir()
        (private / "secret").write_text("secret")
        parent = self.boundaries / ".boundary-generations"
        parent.mkdir()
        (parent / ("gen-" + "a" * 32)).symlink_to(private)
        listing = self.listing("boundaries")
        self.assertFalse(listing["entries"][0]["available"])
        self.assertNotIn("secret", str(listing))

    def test_uploaded_versions_use_exact_digest_and_marker_without_reading_specification_payloads(self):
        old, original = self.specification(payload=b"not JSON: keep original bytes exactly")
        current, current_path = self.specification(payload=b"new original bytes: " * 100_000)
        self.marker("test-product", {"active": True, "digest": current})
        with patch.object(files, "open_file", side_effect=AssertionError("Inventory must not read original payloads")):
            listing = self.listing()
        rows = listing["entries"]
        self.assertEqual([row["version_id"] for row in rows], [current, old])
        self.assertEqual([row["status"] for row in rows], ["current", "previous"])
        self.assertEqual(rows[0]["size_bytes"], current_path.stat().st_size)
        self.assertEqual(original.read_bytes(), b"not JSON: keep original bytes exactly")
        with files.open_file(rows[1]["area"], rows[1]["path"]) as handle:
            self.assertEqual(handle.read(), original.read_bytes())

    def test_archived_product_keeps_history_without_becoming_current(self):
        self.specification()
        (self.deployment / "test-product.json").write_text("deployment original")
        self.marker("test-product", {"active": False})
        listing = self.listing()
        self.assertEqual(len(listing["entries"]), 2)
        self.assertTrue(all(row["status"] == "archived" and row["available"] for row in listing["entries"]))
        self.assertEqual(self.listing(status="current")["total"], 0)
        self.assertEqual(self.listing(status="archived")["total"], 2)

    def test_missing_current_specification_never_enables_deployment_fallback(self):
        old, _ = self.specification()
        missing = "f" * 64
        self.marker("test-product", {"active": True, "digest": missing})
        (self.deployment / "test-product.json").write_bytes(b"old deployment")
        listing = self.listing()
        self.assertEqual(listing["total"], 3)
        unavailable = next(row for row in listing["entries"] if not row["available"])
        self.assertEqual((unavailable["version_id"], unavailable["status"]), (missing, "unavailable"))
        self.assertFalse(any(row["status"] == "current" for row in listing["entries"]))

    def test_marker_corruption_is_bounded_and_does_not_hide_previous_originals(self):
        digest, _ = self.specification()
        marker = self.marker("test-product", {"active": True, "digest": digest})
        for payload in (b'{"active": true, "active":false}', b"{" + b"x" * 1024, b'[]', b'{"active":true,"digest":"invalid"}'):
            with self.subTest(payload=payload[:40]):
                marker.write_bytes(payload)
                listing = self.listing()
                self.assertTrue(listing["warnings"])
                self.assertEqual({row["status"] for row in listing["entries"]}, {"unknown", "unavailable"})
                self.assertTrue(any(row["available"] for row in listing["entries"]))

    def test_unsafe_state_directory_does_not_enable_flat_source(self):
        private = self.root / "private"
        private.mkdir()
        (self.uploaded / ".state").symlink_to(private)
        (self.deployment / "test-product.json").write_text("unchanged original")
        listing = self.listing()
        self.assertEqual(listing["entries"][0]["status"], "unknown")
        self.assertTrue(listing["warnings"])

    def test_deployment_source_precedence_and_legacy_uploads_match_runtime_order(self):
        another = self.root / "another-source"
        another.mkdir()
        (self.deployment / "TEST-PRODUCT.json").write_text("first source")
        (another / "test-product.json").write_text("second source")
        (self.uploaded / "test-product.json").write_text("legacy upload")
        with patch.dict(CONFIG, product_dirs=[self.deployment, another]):
            listing = self.listing()
        rows = listing["entries"]
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["area"] for row in rows if row["status"] == "current"], ["spec-0"])
        self.assertTrue(all(row["product_ident"] == "test-product" for row in rows))

    def test_upload_marker_overrides_both_deployed_and_legacy_flat_sources(self):
        digest, _ = self.specification()
        self.marker("test-product", {"active": True, "digest": digest})
        (self.deployment / "test-product.json").write_text("deployed")
        (self.uploaded / "test-product.json").write_text("legacy")
        listing = self.listing()
        current = [row for row in listing["entries"] if row["status"] == "current"]
        self.assertEqual([row["version_id"] for row in current], [digest])

    def test_saved_original_is_a_content_version_in_the_common_specification_library(self):
        digest, original = self.specification()
        self.marker("test-product", {"active": True, "digest": digest})
        with patch.object(files, "open_file", side_effect=AssertionError("No payload reads")):
            row = self.listing()["entries"][0]
        self.assertTrue(row["versioned"])
        self.assertEqual(row["source"], "Saved original")
        self.assertEqual(row["source_kind"], "saved")
        self.assertEqual(row["location_count"], 1)
        self.assertEqual(row["locations"], ({
            "area": "uploaded-specifications", "path": ".versions/test-product/" + digest + ".json",
            "kind": "file", "source": "Saved original", "source_kind": "saved",
        },))
        self.assertEqual(original.read_bytes(), b'{ "original": true }\n')

    def test_repeated_installed_root_is_one_source_with_multiple_locations(self):
        original = self.deployment / "test-product.json"
        original.write_bytes(b"unchanged installed original")
        with patch.dict(CONFIG, product_dirs=[self.deployment, self.deployment]):
            with patch.object(files, "open_file", side_effect=AssertionError("No payload reads")):
                listing = self.listing()
        self.assertEqual(listing["total"], 1)
        row = listing["entries"][0]
        self.assertEqual((row["area"], row["status"]), ("spec-0", "current"))
        self.assertFalse(row["versioned"])
        self.assertEqual(row["version_label"], "Original installed file")
        self.assertEqual(row["source_kind"], "installed")
        self.assertEqual([location["area"] for location in row["locations"]], ["spec-0", "spec-1"])
        self.assertEqual(row["location_count"], 2)
        self.assertNotIn("_file_identity", row)
        self.assertNotIn(str(self.root), str(listing))

    def test_distinct_installed_copies_are_not_merged_by_name_size_or_matching_bytes(self):
        another = self.root / "another-installed-source"
        another.mkdir()
        for directory in (self.deployment, another):
            (directory / "test-product.json").write_bytes(b"same bytes without a recorded fingerprint")
        with patch.dict(CONFIG, product_dirs=[self.deployment, another]):
            listing = self.listing()
        self.assertEqual(listing["total"], 2)
        self.assertEqual({row["status"] for row in listing["entries"]}, {"current", "previous"})
        self.assertTrue(all(not row["versioned"] and row["location_count"] == 1 for row in listing["entries"]))
        self.assertTrue(all("digest" not in row for row in listing["entries"]))
        labels = {row["status"]: row["status_label"] for row in listing["entries"]}
        self.assertEqual(labels, {"current": "Current", "previous": "Not selected"})
        self.assertFalse(any(row["status_label"] == "Previous" for row in listing["entries"]))

    def test_retained_file_and_flat_alias_for_different_product_do_not_merge(self):
        digest, _ = self.specification()
        self.marker("test-product", {"active": True, "digest": digest})
        directory = self.uploaded / ".versions" / "test-product"
        with patch.dict(CONFIG, product_dirs=[directory]):
            listing = self.listing()
        self.assertEqual(listing["total"], 2)
        self.assertEqual({row["product_ident"] for row in listing["entries"]}, {"test-product", digest})
        self.assertEqual(len([row for row in listing["entries"] if row["versioned"]]), 1)

    def test_simplified_history_keeps_current_installed_source_without_inventing_a_digest(self):
        (self.deployment / "test-product.json").write_bytes(b"first installed source")
        (self.uploaded / "test-product.json").write_bytes(b"legacy installed source")
        with patch.object(files, "open_file", side_effect=AssertionError("No payload reads")):
            listing = self.listing(include_sources=False)
        self.assertEqual(listing["total"], 1)
        self.assertEqual((listing["version_count"], listing["source_count"]), (0, 1))
        row = listing["entries"][0]
        self.assertEqual((row["area"], row["status"]), ("spec-0", "current"))
        self.assertFalse(row["versioned"])
        self.assertNotIn("digest", row)
        self.assertNotIn("SHA-256", row["version_label"])
        detailed = self.listing(include_sources=True)
        self.assertEqual((detailed["total"], detailed["source_count"]), (2, 2))

    def test_simplified_history_filters_source_details_before_search_and_pagination(self):
        for index in range(4):
            self.specification(payload=str(index).encode())
        (self.deployment / "test-product.json").write_bytes(b"installed source")
        (self.uploaded / "test-product.json").write_bytes(b"legacy source")
        current = self.listing(include_sources=False, page_size=2, page=2)
        self.assertEqual((current["total"], current["page"], len(current["entries"])), (5, 2, 2))
        self.assertEqual((current["version_count"], current["source_count"]), (4, 1))
        self.assertTrue(current["has_previous"] and current["has_next"])
        previous = self.listing(include_sources=False, status="previous", query="test-product")
        self.assertEqual((previous["total"], previous["version_count"], previous["source_count"]), (4, 4, 0))
        self.assertTrue(all(row["versioned"] for row in previous["entries"]))

    def test_simplified_history_preserves_archived_state_and_never_selects_installed_fallback(self):
        self.marker("test-product", {"active": False})
        (self.deployment / "test-product.json").write_bytes(b"must not become current")
        self.assertEqual(self.listing(include_sources=False, status="current")["total"], 0)
        detailed = self.listing(include_sources=True, status="archived")
        self.assertEqual(detailed["total"], 2)
        self.assertEqual((detailed["version_count"], detailed["source_count"]), (1, 1))
        original = next(row for row in detailed["entries"] if not row["versioned"])
        self.assertTrue(original["available"])
        with files.open_file(original["area"], original["path"]) as handle:
            self.assertEqual(handle.read(), b"must not become current")
        archived = self.listing(include_sources=False, status="archived")
        self.assertEqual(archived["total"], 1)
        self.assertTrue(archived["entries"][0]["versioned"])
        self.assertFalse(archived["entries"][0]["available"])
        self.assertEqual(archived["entries"][0]["locations"], ())
        # An archive with no remaining physical original is still discoverable.
        (self.deployment / "test-product.json").unlink()
        listing = self.listing(include_sources=False)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["entries"][0]["status"], "archived")
        self.assertTrue(listing["entries"][0]["versioned"])
        self.assertFalse(listing["entries"][0]["available"])

    def test_simplified_history_keeps_missing_current_and_invalid_state_placeholders(self):
        self.marker("test-product", {"active": True, "digest": "f" * 64})
        (self.deployment / "test-product.json").write_bytes(b"must not become current")
        listing = self.listing(include_sources=False)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["entries"][0]["status"], "unavailable")
        self.marker("test-product", {"active": True, "digest": "not a digest"})
        listing = self.listing(include_sources=False)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["entries"][0]["status"], "unavailable")
        self.assertTrue(listing["entries"][0]["versioned"])

    def test_configured_upload_root_does_not_duplicate_legacy_originals(self):
        (self.uploaded / "test-product.json").write_text("legacy original")
        with patch.dict(CONFIG, product_dirs=[self.uploaded]):
            listing = self.listing()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["entries"][0]["status"], "current")

    def test_unsafe_retained_specification_files_do_not_become_downloadable(self):
        digest, original = self.specification()
        self.marker("test-product", {"active": True, "digest": digest})
        link = self.root / "hard-link.json"
        os.link(original, link)
        listing = self.listing()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["entries"][0]["status"], "unavailable")
        self.assertFalse(listing["entries"][0]["available"])
        self.assertEqual(listing["skipped_count"], 1)

    def test_search_status_and_pagination_have_bounded_stable_pages(self):
        for index in range(7):
            self.specification("product-a", payload=str(index).encode())
        self.specification("product-b")
        listing = self.listing(query="product-a", status="previous", page=2, page_size=3)
        self.assertEqual((listing["total"], listing["page"], len(listing["entries"])), (7, 2, 3))
        self.assertTrue(listing["has_previous"] and listing["has_next"])
        self.assertEqual(self.listing(page="invalid")["page"], 1)
        self.assertEqual(self.listing(page=500, page_size=3)["page"], 3)
        with patch.object(versions, "MAX_SCAN_ENTRIES", 3):
            limited = self.listing()
        self.assertTrue(limited["scan_limited"])
        self.assertLessEqual(limited["scanned_count"], 3)
        self.assertTrue(limited["warnings"])

    def test_missing_sources_have_user_safe_warnings_without_absolute_paths(self):
        with patch.dict(CONFIG, boundary_dir=self.root / "missing-boundaries", product_dirs=[self.root / "missing-specs"]):
            for kind in ("boundaries", "specifications"):
                listing = self.listing(kind)
                self.assertEqual(listing["total"], 0)
                self.assertTrue(listing["warnings"])
                self.assertNotIn(str(self.root), str(listing))

    def test_invalid_inventory_kind_fails_closed(self):
        with self.assertRaises(files.StorageError) as raised:
            self.listing("../../private")
        self.assertEqual(raised.exception.status_code, 404)


class StorageVersionCatalogTests(VersionFixture, TestCase):
    def catalog_definition(self, digest, *, ident="test-product", description="Retained catalog description"):
        return QcDefinition.objects.create(
            product_ident=ident, digest=digest, description=description,
            document={"never_needed_by_storage_inventory": "x" * 10000}, source_path="upload:" + ident + ".json",
        )

    def test_catalog_enrichment_reuses_existing_revisions_with_three_scalar_queries(self):
        digest, _ = self.specification()
        self.marker("test-product", {"active": True, "digest": digest})
        product = Product.objects.create(ident="test-product", name="Readable product name")
        definition = QcDefinition.objects.create(
            product_ident="test-product", digest=digest, description="A readable specification",
            document={"never_needed_by_storage_inventory": "x" * 10000}, source_path="upload:test-product.json",
        )
        release = ProductRelease.objects.create(
            product=product, release_key="definition:test-product", revision=3,
            description="Current upload", catalog_digest="c" * 64, source_kind="upload", is_current=True,
        )
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        with CaptureQueriesContext(connection) as queries:
            listing = versions.list_versions("specifications")
        self.assertEqual(len(queries), 3)
        self.assertTrue(all('"document"' not in item["sql"] for item in queries))
        row = listing["entries"][0]
        self.assertEqual(row["product_name"], product.name)
        self.assertEqual(row["description"], definition.description)
        self.assertEqual(row["imported_at"], definition.imported_at.isoformat())
        self.assertEqual(row["revision_labels"], ("Revision 3",))
        self.assertEqual(row["version_label"], "Revision 3")
        self.assertEqual(row["version_id"], digest)
        self.assertTrue(row["versioned"])
        self.assertEqual(row["location_count"], 1)

    def test_catalog_only_revision_remains_visible_with_no_original_payload_reads(self):
        digest = "a" * 64
        definition = self.catalog_definition(digest, description="Older approved specification")
        with patch.object(files, "open_file", side_effect=AssertionError("No original payload reads")):
            with CaptureQueriesContext(connection) as queries:
                listing = versions.list_versions("specifications")
        self.assertEqual(listing["total"], 1)
        self.assertTrue(all('"document"' not in item["sql"] for item in queries))
        row = listing["entries"][0]
        self.assertEqual(row["version_id"], digest)
        self.assertEqual(row["description"], definition.description)
        self.assertEqual(row["imported_at"], definition.imported_at.isoformat())
        self.assertTrue(row["catalog_only"])
        self.assertFalse(row["available"])
        self.assertEqual(row["selection_paths"], ())
        self.assertEqual(row["status"], "unavailable")
        self.assertEqual(row["source"], "Catalog history retained")
        self.assertEqual(row["source_kind"], "catalog")
        self.assertTrue(row["versioned"])
        self.assertEqual(row["locations"], ())
        self.assertEqual(row["location_count"], 0)
        self.assertIn("Original file not located", row["message"])

    def test_same_named_deployment_file_does_not_claim_the_catalog_fingerprint(self):
        digest = "b" * 64
        self.catalog_definition(digest)
        original = self.deployment / "test-product.json"
        original.write_bytes(b"different original file, whose bytes must not be parsed")
        listing = versions.list_versions("specifications")
        self.assertEqual(listing["total"], 2)
        deployment = next(row for row in listing["entries"] if row["available"])
        stored = next(row for row in listing["entries"] if row["catalog_only"])
        self.assertNotIn("digest", deployment)
        self.assertNotEqual(deployment["version_id"], digest)
        self.assertEqual(stored["version_id"], digest)
        self.assertEqual(original.read_bytes(), b"different original file, whose bytes must not be parsed")

    def test_missing_current_original_reconciles_with_one_catalog_history_row(self):
        digest = "c" * 64
        self.marker("test-product", {"active": True, "digest": digest})
        self.catalog_definition(digest, description="Known missing current original")
        listing = versions.list_versions("specifications")
        self.assertEqual(listing["total"], 1)
        row = listing["entries"][0]
        self.assertEqual((row["version_id"], row["status"]), (digest, "unavailable"))
        self.assertFalse(row["available"])
        self.assertFalse(row["catalog_only"])
        self.assertEqual(row["description"], "Known missing current original")

    def test_catalog_current_reference_does_not_activate_missing_originals(self):
        digest = "d" * 64
        definition = self.catalog_definition(digest)
        product = Product.objects.create(ident="test-product", name="Catalog product")
        release = ProductRelease.objects.create(
            product=product, release_key="definition:test-product", revision=5,
            description="Current catalog release", catalog_digest="e" * 64, source_kind="upload", is_current=True,
        )
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        listing = versions.list_versions("specifications")
        row = listing["entries"][0]
        self.assertTrue(row["catalog_is_current"])
        self.assertEqual(row["catalog_status_label"], "Current catalog revision")
        self.assertEqual(row["version_label"], "Revision 5")
        self.assertEqual(row["product_name"], "Catalog product")
        self.assertEqual(row["status"], "unavailable")
        self.assertFalse((self.uploaded / ".state").exists())

    def test_catalog_history_is_paginated_and_metadata_queries_do_not_grow_per_row(self):
        for index in range(7):
            self.catalog_definition(f"{index:064x}", description="Searchable older revision")
        with CaptureQueriesContext(connection) as queries:
            listing = versions.list_versions("specifications", page_size=3, page=2, query="Searchable older")
        self.assertEqual(len(queries), 3)
        self.assertEqual((listing["total"], listing["page"], len(listing["entries"])), (7, 2, 3))
        self.assertTrue(listing["has_previous"] and listing["has_next"])
        with patch.object(versions, "MAX_CATALOG_ROWS", 2):
            limited = versions.list_versions("specifications")
        self.assertEqual(limited["total"], 2)
        self.assertTrue(any("inventory limit" in message for message in limited["warnings"]))

    def test_catalog_failure_preserves_file_inventory_and_explains_missing_metadata(self):
        self.specification()
        with patch.object(Product.objects, "filter", side_effect=DatabaseError("private SQL detail")):
            listing = versions.list_versions("specifications")
        self.assertEqual(listing["total"], 1)
        self.assertTrue(listing["entries"][0]["available"])
        self.assertTrue(listing["warnings"])
        self.assertNotIn("private SQL", str(listing))

    def test_file_only_inventory_does_not_query_or_modify_the_catalog(self):
        digest, original = self.specification()
        marker = self.marker("test-product", {"active": True, "digest": digest})
        before = {path: path.read_bytes() for path in (original, marker)}
        with CaptureQueriesContext(connection) as queries:
            listing = self.listing()
        self.assertEqual(len(queries), 0)
        self.assertEqual(listing["entries"][0]["status"], "current")
        self.assertEqual({path: path.read_bytes() for path in before}, before)
