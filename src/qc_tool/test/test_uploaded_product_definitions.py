"""Shared frontend/worker discovery of uploaded product specifications."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from qc_tool.common import CONFIG
from qc_tool.common import INVALID_PRODUCT_DESCRIPTION
from qc_tool.common import QCException
from qc_tool.common import compile_job_report_data
from qc_tool.common import compose_job_dir
from qc_tool.common import copy_product_definition_to_job
from qc_tool.common import current_product_specification_state
from qc_tool.common import get_product_definitions
from qc_tool.common import get_product_descriptions
from qc_tool.common import load_product_definition
from qc_tool.common import load_product_definition_from_job
from qc_tool.common import locate_product_definition
from qc_tool.common import product_definition_directories
from qc_tool.common import store_job_result


class ProductDefinitionStorageFixture:
    def setUp(self):
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.work = self.root / "work"
        self.uploads = self.work / "product_definitions"
        config_patch = patch.dict(
            CONFIG, {"product_dirs": [self.source], "work_dir": self.work}
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def write_definition(self, directory, name, description):
        path = directory / (name + ".json")
        path.write_text(
            json.dumps({"description": description, "steps": []}),
            encoding="utf-8",
        )
        return path


class UploadedProductDefinitionDiscoveryTests(ProductDefinitionStorageFixture, TestCase):
    def test_catalog_reads_do_not_create_upload_storage(self):
        path = self.write_definition(self.source, "source", "Source product")

        self.assertEqual(product_definition_directories(), [self.source])
        self.assertEqual(locate_product_definition("source"), path)
        self.assertEqual(get_product_descriptions(), {"source": "Source product"})
        self.assertEqual(get_product_definitions(), ["source"])
        self.assertFalse(self.work.exists())

    def test_uploads_are_discovered_after_an_initial_read_without_restart(self):
        self.assertEqual(get_product_definitions(), [])
        with self.assertRaises(QCException):
            locate_product_definition("new-product")

        self.uploads.mkdir(parents=True)
        path = self.write_definition(self.uploads, "new-product", "New product")

        self.assertEqual(
            product_definition_directories(), [self.source, self.uploads]
        )
        self.assertEqual(locate_product_definition("NEW-PRODUCT"), path)
        self.assertEqual(
            load_product_definition("new-product"),
            {"description": "New product", "steps": [], "product_ident": "new-product"},
        )
        self.assertEqual(get_product_descriptions(), {"new-product": "New product"})
        self.assertEqual(get_product_definitions(), ["new-product"])
        self.assertEqual(CONFIG["product_dirs"], [self.source])

    def test_source_precedence_and_canonical_deduplication_are_consistent(self):
        other_source = self.root / "second-source"
        other_source.mkdir()
        self.uploads.mkdir(parents=True)
        first_path = self.write_definition(self.source, "PRODUCT", "First source")
        second_path = self.write_definition(other_source, "product", "Second source")
        self.write_definition(self.uploads, "product", "Uploaded product")
        CONFIG["product_dirs"] = [self.source, other_source]

        self.assertEqual(locate_product_definition("product"), first_path)
        self.assertEqual(get_product_descriptions(), {"product": "First source"})
        self.assertEqual(load_product_definition("product")["description"], "First source")
        self.assertEqual(get_product_definitions(), ["product"])

        CONFIG["product_dirs"] = [other_source, self.source]
        self.assertEqual(locate_product_definition("product"), second_path)
        self.assertEqual(get_product_descriptions(), {"product": "Second source"})
        self.assertEqual(get_product_definitions(), ["product"])

    def test_duplicate_identifiers_in_one_source_select_the_same_file(self):
        expected = self.write_definition(self.source, "PRODUCT", "Uppercase filename")
        if (self.source / "product.json").exists():
            self.skipTest("Duplicate case variants require a case-sensitive filesystem")
        self.write_definition(self.source, "product", "Lowercase filename")

        self.assertEqual(locate_product_definition("product"), expected)
        self.assertEqual(
            get_product_descriptions(), {"product": "Uppercase filename"}
        )
        self.assertEqual(get_product_definitions(), ["product"])

    def test_invalid_uploaded_identifiers_cannot_alias_valid_products(self):
        self.uploads.mkdir(parents=True)
        for name in ("paß", "list", "white space"):
            self.write_definition(self.uploads, name, "Invalid identifier")

        self.assertEqual(get_product_definitions(), [])
        with self.assertLogs("qc_tool.common", level="WARNING"):
            self.assertEqual(get_product_descriptions(), {})
        for identifier in ("pass", "paß", "list", "white space"):
            with self.subTest(identifier=identifier):
                with self.assertRaises(QCException):
                    locate_product_definition(identifier)

    def test_missing_configured_sources_still_fail_catalog_listing(self):
        CONFIG["product_dirs"] = [self.root / "missing"]
        self.uploads.mkdir(parents=True)
        path = self.write_definition(self.uploads, "uploaded", "Uploaded product")

        # Location historically skips nonexistent sources, while listing
        # reports misconfiguration instead of silently hiding it.
        self.assertEqual(locate_product_definition("uploaded"), path)
        with self.assertRaises(FileNotFoundError):
            get_product_descriptions()
        with self.assertRaises(FileNotFoundError):
            get_product_definitions()

    def test_optional_path_must_be_a_directory(self):
        self.work.mkdir()
        self.uploads.write_text("not a directory", encoding="utf-8")

        self.assertEqual(product_definition_directories(), [self.source])
        self.assertEqual(get_product_descriptions(), {})
        self.assertEqual(get_product_definitions(), [])

    def test_configured_upload_directory_is_not_added_twice(self):
        self.uploads.mkdir(parents=True)
        CONFIG["product_dirs"] = [self.source, self.uploads]

        self.assertEqual(
            product_definition_directories(), [self.source, self.uploads]
        )


class VersionedProductSpecificationDiscoveryTests(ProductDefinitionStorageFixture, TestCase):
    def write_version(self, ident, description):
        payload = json.dumps({"description": description, "steps": []}).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        directory = self.uploads / ".versions" / ident
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (digest + ".json")
        path.write_bytes(payload)
        return digest, path

    def write_state(self, ident, state):
        directory = self.uploads / ".state"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (ident + ".json")
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    def test_new_version_overrides_configured_and_legacy_uploaded_files(self):
        self.write_definition(self.source, "product", "Configured recipe")
        self.uploads.mkdir(parents=True)
        self.write_definition(self.uploads, "product", "Old uploaded recipe")
        digest, path = self.write_version("product", "Current version")
        self.write_state("product", {"active": True, "digest": digest})

        self.assertEqual(locate_product_definition("product"), path)
        self.assertEqual(load_product_definition("product")["description"], "Current version")
        self.assertEqual(get_product_descriptions(), {"product": "Current version"})
        self.assertEqual(get_product_definitions(), ["product"])
        self.assertEqual(
            current_product_specification_state("PRODUCT"),
            {"active": True, "digest": digest},
        )

    def test_active_selection_changes_without_restart_and_keeps_old_bytes(self):
        first_digest, first = self.write_version("product", "First version")
        self.write_state("product", {"active": True, "digest": first_digest})
        self.assertEqual(locate_product_definition("product"), first)
        original_bytes = first.read_bytes()

        second_digest, second = self.write_version("product", "Second version")
        self.write_state("product", {"active": True, "digest": second_digest})

        self.assertEqual(locate_product_definition("product"), second)
        self.assertEqual(get_product_descriptions(), {"product": "Second version"})
        self.assertEqual(get_product_definitions(), ["product"])
        self.assertEqual(first.read_bytes(), original_bytes)

    def test_archived_state_hides_every_source_and_retains_versions(self):
        self.write_definition(self.source, "product", "Configured recipe")
        digest, version = self.write_version("product", "Uploaded version")
        self.write_state("product", {"active": True, "digest": digest})
        self.assertEqual(get_product_definitions(), ["product"])

        self.write_state("product", {"active": False})

        with self.assertRaisesRegex(QCException, "archived"):
            locate_product_definition("product")
        self.assertEqual(get_product_definitions(), [])
        self.assertEqual(get_product_descriptions(), {})
        self.assertTrue(version.is_file())

    def test_invalid_active_state_never_falls_back_to_configured_file(self):
        self.write_definition(self.source, "product", "Configured recipe")
        for state in (
            [], {"active": 1}, {"active": "true"}, {"active": True},
            {"active": True, "digest": "../escape"},
            {"active": True, "digest": "A" * 64},
        ):
            with self.subTest(state=state):
                self.write_state("product", state)
                self.assert_invalid_runtime_product()

    def test_malformed_or_duplicate_state_keys_never_fall_back(self):
        self.write_definition(self.source, "product", "Configured recipe")
        marker = self.write_state("product", {"active": False})
        for payload in (b"not json", b'{"active":false,"active":true}', b"\xff"):
            with self.subTest(payload=payload):
                marker.write_bytes(payload)
                self.assert_invalid_runtime_product()

    def test_missing_or_changed_version_never_falls_back_to_configured_file(self):
        self.write_definition(self.source, "product", "Configured recipe")
        digest, version = self.write_version("product", "Uploaded version")
        self.write_state("product", {"active": True, "digest": digest})
        version.unlink()
        self.assert_invalid_runtime_product()

        version.write_text('{"description": "tampered", "steps": []}', encoding="utf-8")
        self.assert_invalid_runtime_product()

    def test_symlinked_marker_and_version_cannot_select_external_bytes(self):
        self.write_definition(self.source, "product", "Configured recipe")
        digest, version = self.write_version("product", "Uploaded version")
        marker = self.write_state("product", {"active": True, "digest": digest})
        original_marker = self.root / "outside-state.json"
        marker.rename(original_marker)
        marker.symlink_to(original_marker)
        self.assert_invalid_runtime_product()

        marker.unlink()
        original_marker.rename(marker)
        original_version = self.root / "outside-version.json"
        version.rename(original_version)
        version.symlink_to(original_version)
        self.assert_invalid_runtime_product()

    def test_missing_state_does_not_create_storage(self):
        self.assertIsNone(current_product_specification_state("product"))
        self.assertFalse(self.work.exists())

    def assert_invalid_runtime_product(self):
        with self.assertRaises(QCException):
            locate_product_definition("product")
        with self.assertLogs("qc_tool.common", level="WARNING"):
            self.assertEqual(
                get_product_descriptions(), {"product": INVALID_PRODUCT_DESCRIPTION}
            )
        with self.assertLogs("qc_tool.common", level="WARNING"):
            self.assertEqual(get_product_definitions(), [])


class JobProductSpecificationSnapshotTests(ProductDefinitionStorageFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.job_uuid = str(uuid4())
        self.job_dir = compose_job_dir(self.job_uuid)
        self.job_dir.mkdir(parents=True)

    def write_digest_snapshot(self, description="Historical recipe", payload=None):
        if payload is None:
            payload = json.dumps({"description": description, "steps": []}).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        path = self.job_dir / (digest + ".json")
        path.write_bytes(payload)
        return path

    def test_versioned_source_is_copied_under_canonical_product_name(self):
        payload = b'{"description": "Uploaded recipe", "steps": []}'
        digest = hashlib.sha256(payload).hexdigest()
        versions = self.uploads / ".versions" / "product"
        versions.mkdir(parents=True)
        source = versions / (digest + ".json")
        source.write_bytes(payload)
        states = self.uploads / ".state"
        states.mkdir()
        (states / "product.json").write_text(json.dumps({"active": True, "digest": digest}))

        copy_product_definition_to_job(self.job_uuid, "PRODUCT")

        self.assertEqual((self.job_dir / "product.json").read_bytes(), payload)
        self.assertFalse((self.job_dir / source.name).exists())
        self.assertEqual(
            load_product_definition_from_job(self.job_uuid, "product")["description"],
            "Uploaded recipe",
        )

    def test_historical_digest_snapshot_compiles_without_current_product(self):
        self.write_digest_snapshot()
        store_job_result({
            "job_uuid": self.job_uuid,
            "product_ident": "product",
            "filename": "delivery.zip",
            "status": "ok",
            "steps": [],
        })
        with patch("qc_tool.common.load_product_definition", side_effect=AssertionError("Current recipe must not be read")):
            report = compile_job_report_data(self.job_uuid)

        self.assertEqual(report["description"], "Historical recipe")
        self.assertEqual(report["filename"], "delivery.zip")
        self.assertEqual(report["status"], "ok")

    def test_named_snapshot_is_case_insensitive_and_takes_precedence(self):
        self.write_definition(self.job_dir, "PRODUCT", "Named historical recipe")
        self.write_digest_snapshot()

        definition = load_product_definition_from_job(self.job_uuid, "product")

        self.assertEqual(definition["description"], "Named historical recipe")

    def test_multiple_digest_snapshots_are_not_guessed(self):
        self.write_digest_snapshot("First recipe")
        self.write_digest_snapshot("Second recipe")

        with self.assertRaisesRegex(QCException, "ambiguous"):
            load_product_definition_from_job(self.job_uuid, "product")

    def test_multiple_case_variants_are_not_guessed(self):
        self.write_definition(self.job_dir, "PRODUCT", "Uppercase recipe")
        if (self.job_dir / "product.json").exists():
            self.skipTest("Duplicate case variants require a case-sensitive filesystem")
        self.write_definition(self.job_dir, "product", "Lowercase recipe")

        with self.assertRaisesRegex(QCException, "ambiguous"):
            load_product_definition_from_job(self.job_uuid, "product")

    def test_invalid_named_snapshot_does_not_fall_back_to_digest_snapshot(self):
        (self.job_dir / "product.json").write_text("not JSON")
        self.write_digest_snapshot()

        with self.assertRaisesRegex(QCException, "unavailable or invalid"):
            load_product_definition_from_job(self.job_uuid, "product")

    def test_changed_digest_snapshot_is_rejected(self):
        path = self.write_digest_snapshot()
        path.write_text('{"description": "Changed recipe", "steps": []}')

        with self.assertRaisesRegex(QCException, "unavailable or invalid"):
            load_product_definition_from_job(self.job_uuid, "product")

    def test_symlinked_snapshots_cannot_read_external_files(self):
        for digest_named in (False, True):
            with self.subTest(digest_named=digest_named):
                path = (
                    self.write_digest_snapshot() if digest_named else
                    self.write_definition(self.job_dir, "product", "Recipe")
                )
                external = self.root / "external.json"
                path.rename(external)
                path.symlink_to(external)
                with self.assertRaisesRegex(QCException, "unavailable or invalid"):
                    load_product_definition_from_job(self.job_uuid, "product")
                path.unlink()
                external.unlink()

    def test_digest_named_directory_is_rejected(self):
        (self.job_dir / ("a" * 64 + ".json")).mkdir()

        with self.assertRaisesRegex(QCException, "unavailable or invalid"):
            load_product_definition_from_job(self.job_uuid, "product")

    def test_invalid_snapshot_json_is_rejected_even_with_matching_digest(self):
        for payload in (b"not JSON", b"[]", b'{}', b'\xff'):
            with self.subTest(payload=payload):
                path = self.write_digest_snapshot(payload=payload)
                with self.assertRaisesRegex(QCException, "unavailable or invalid"):
                    load_product_definition_from_job(self.job_uuid, "product")
                path.unlink()

    def test_missing_snapshot_never_uses_current_product(self):
        self.write_definition(self.source, "product", "Today's recipe")
        (self.job_dir / "result.json").write_text('{"product_ident": "product", "steps": []}')

        with self.assertRaisesRegex(QCException, "has not been found"):
            load_product_definition_from_job(self.job_uuid, "product")

    def test_invalid_product_identifier_is_rejected(self):
        for product_ident in ("../external", None, "pa\u00df"):
            with self.subTest(product_ident=product_ident):
                with self.assertRaisesRegex(QCException, "identifier is invalid"):
                    load_product_definition_from_job(self.job_uuid, product_ident)
