"""Retained restore copies protect shared files even with an empty active DB."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path

from qc_tool.common import CONFIG
from qc_tool.database.transfers import recovery_files, storage_pins, store
from qc_tool.database.transfers.archive import ArchiveLimits
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.services.storage_admin.references import (
    StorageReferenceError, assert_unreferenced, describe_references,
)


def empty_view(request):
    return HttpResponse()


urlpatterns = [path("admin/database/", empty_view, name="admin_data_transfer")]


class PinFixtures:
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-retained-pin-")))
        self.transfers = self.root / "transfers"
        self.incoming = self.root / "incoming"
        self.work = self.root / "work"
        self.published = self.root / "published"
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=self.transfers, MEDIA_ROOT=self.incoming,
                                           ROOT_URLCONF=__name__))
        self.enterContext(patch.dict(CONFIG, {"work_dir": self.work, "incoming_dir": self.incoming,
                                               "submission_dir": self.published}))

    def plan(self, entries=None, *, roots=None):
        return SimpleNamespace(archive=SimpleNamespace(entries=tuple(entries if entries is not None else [
            {"root": "incoming", "key": "retained-owner/original.zip", "sha256": "a" * 64, "size": 123},
        ])), roots=roots or {"incoming": self.incoming, "work": self.work, "submissions": self.published})

    def operation(self):
        identity = str(uuid4())
        store.operation_dir(identity, create=True)
        return {"id": identity, "destination": {"database": "retained_database"}}

    def pin(self, entries=None):
        operation = self.operation()
        storage_pins.pin_restore_files(operation, self.plan(entries))
        return operation, store.operation_dir(operation["id"]) / storage_pins.FILENAME


class StoragePinTests(PinFixtures, SimpleTestCase):
    def aliased_specifications(self, *, canonical=True):
        specifications = self.root / "specifications" if canonical else self.work / "product_definitions"
        roots = {"work": self.work, "product-0": specifications,
                 "incoming": self.incoming, "boundaries": self.root / "boundaries",
                 "submissions": self.published}
        if canonical:
            roots["specifications"] = specifications
        for root in set(roots.values()):
            root.mkdir(parents=True, exist_ok=True)
        original = specifications / "original.json"
        original.write_bytes(b'{"fixture": "original specification bytes"}')
        inventory, entries, _fingerprint, _size = recovery_files.snapshot(limits=ArchiveLimits(), roots=roots)
        self.assertEqual(len(entries), 2)
        return original, inventory, entries

    def test_upgrade_retains_one_physical_file_with_two_configured_archive_identities(self):
        original, inventory, entries = self.aliased_specifications()
        operation = self.operation()
        document = storage_pins.pin_existing_files(operation, inventory.sources, entries)
        self.assertEqual(len(document["files"]), 1)
        retained = document["files"][0]
        self.assertEqual(Path(document["roots"][retained["root"]]) / retained["key"], original)
        with patch.object(store, "write_json", side_effect=AssertionError("idempotent pin rewrite")):
            repeated = storage_pins.pin_existing_files(operation, reversed(inventory.sources), reversed(entries))
        self.assertEqual(repeated, document)
        self.assertEqual(original.read_bytes(), b'{"fixture": "original specification bytes"}')

    def test_upgrade_refuses_aliases_with_conflicting_checksums_without_creating_pin(self):
        _original, inventory, entries = self.aliased_specifications()
        operation = self.operation()
        entries[1] = {**entries[1], "sha256": "0" * 64}
        with self.assertRaisesMessage(TransferError, "aliases disagree"):
            storage_pins.pin_existing_files(operation, inventory.sources, entries)
        self.assertFalse((store.operation_dir(operation["id"]) / storage_pins.FILENAME).exists())

    def test_upgrade_deduplicates_legacy_aliases_with_different_parent_storage_roots(self):
        original, inventory, entries = self.aliased_specifications(canonical=False)
        self.assertEqual(len({source.storage_root for source in inventory.sources}), 2)
        operation = self.operation()
        document = storage_pins.pin_existing_files(operation, inventory.sources, entries)
        self.assertEqual(len(document["files"]), 1)
        retained = document["files"][0]
        self.assertEqual(Path(document["roots"][retained["root"]]) / retained["key"], original)
        with patch.object(store, "write_json", side_effect=AssertionError("idempotent pin rewrite")):
            repeated = storage_pins.pin_existing_files(operation, reversed(inventory.sources), reversed(entries))
        self.assertEqual(repeated, document)

    def test_upgrade_refuses_ambiguous_or_incomplete_source_inventory(self):
        _original, inventory, entries = self.aliased_specifications()
        operation = self.operation()
        with self.assertRaisesMessage(TransferError, "repeats a logical"):
            storage_pins.pin_existing_files(operation, [*inventory.sources, inventory.sources[0]], entries)
        with self.assertRaisesMessage(TransferError, "omits a physical"):
            storage_pins.pin_existing_files(operation, inventory.sources, entries[:1])
        self.assertFalse((store.operation_dir(operation["id"]) / storage_pins.FILENAME).exists())

    def test_upgrade_pins_dedicated_specification_mount_at_original_physical_path(self):
        specifications = self.root / "specifications"
        boundaries = self.root / "boundaries"
        roots = {"work": self.work, "specifications": specifications, "incoming": self.incoming,
                 "boundaries": boundaries, "submissions": self.published}
        for root in roots.values():
            root.mkdir()
        original = specifications / "original.json"
        original.write_bytes(b'{"fixture": "original specification bytes"}')
        inventory, entries, _fingerprint, _size = recovery_files.snapshot(limits=ArchiveLimits(), roots=roots)
        self.assertEqual(entries[0]["key"], "product_definitions/original.json")
        document = storage_pins.pin_existing_files(self.operation(), inventory.sources, entries)
        retained = document["files"][0]
        self.assertEqual(Path(document["roots"][retained["root"]]) / retained["key"], original)
        self.assertEqual(original.read_bytes(), b'{"fixture": "original specification bytes"}')
        self.assertFalse((self.work / "product_definitions").exists())

    def test_absent_transfer_storage_is_not_created_by_read_or_empty_restore(self):
        with patch.object(store, "directory", side_effect=AssertionError("read-side creation")):
            self.assertEqual(storage_pins.describe_pins("incoming", "owner/file.zip"), [])
            self.assertIsNone(storage_pins.pin_restore_files({}, self.plan([])))
        self.assertFalse(self.transfers.exists())

    def test_pin_covers_created_and_reused_files_and_returns_only_admin_navigation(self):
        operation, pin_path = self.pin()
        before = pin_path.stat().st_mtime_ns
        document = store.read_json(pin_path)
        self.assertEqual(document["files"], list(self.plan().archive.entries))
        self.assertEqual(document["destination_database"], "retained_database")
        with patch.object(store, "write_json", side_effect=AssertionError("read-side write")), \
                patch.object(store, "directory", side_effect=AssertionError("read-side initialization")):
            references = storage_pins.describe_pins("incoming", "retained-owner/original.zip")
            self.assertEqual(len(references), 1)
            self.assertEqual(references[0]["kind"], "retained_restore")
            self.assertIn("retained_database", references[0]["label"])
            self.assertEqual(urlsplit(references[0]["url"]).path, "/admin/database/")
            self.assertEqual(parse_qs(urlsplit(references[0]["url"]).query), {"operation": [operation["id"]]})
        self.assertEqual(pin_path.stat().st_mtime_ns, before)
        with patch.object(store, "write_json", side_effect=AssertionError("idempotent rewrite")):
            storage_pins.pin_restore_files(operation, self.plan())

    def test_directory_queries_and_job_published_aliases_cover_exact_configured_paths(self):
        job_key = "job_" + uuid4().hex + "/output.d/report.pdf"
        self.pin([
            {"root": "work", "key": job_key, "sha256": "b" * 64, "size": 12},
            {"root": "submissions", "key": "published/original/report.pdf", "sha256": "c" * 64, "size": 25},
        ])
        self.assertEqual(len(storage_pins.describe_pins("jobs", job_key)), 1)
        self.assertEqual(len(storage_pins.describe_pins("jobs", job_key.split("/")[0], is_directory=True)), 1)
        self.assertEqual(len(storage_pins.describe_pins("published", "published/original/report.pdf")), 1)
        self.assertEqual(len(storage_pins.describe_pins("submissions", "published", is_directory=True)), 1)
        self.assertEqual(storage_pins.describe_pins("incoming", "someone/report.pdf"), [])

    def test_same_relative_name_on_another_configured_root_is_not_the_same_file(self):
        self.pin()
        with override_settings(MEDIA_ROOT=self.root / "different-incoming"):
            self.assertEqual(storage_pins.describe_pins("incoming", "retained-owner/original.zip"), [])

    def test_changed_existing_pin_cannot_release_or_reassign_retained_files(self):
        operation, pin_path = self.pin()
        original = pin_path.read_bytes()
        different = list(self.plan().archive.entries)
        different[0] = {**different[0], "sha256": "b" * 64}
        with self.assertRaisesMessage(TransferError, "pin changed"):
            storage_pins.pin_restore_files(operation, self.plan(different))
        self.assertEqual(pin_path.read_bytes(), original)
        self.assertIsNone(storage_pins.pin_restore_files(operation, self.plan([])))
        self.assertEqual(pin_path.read_bytes(), original)

    def test_malformed_unsafe_or_unavailable_pins_fail_closed(self):
        _operation, pin_path = self.pin()
        original = store.read_json(pin_path)
        for mode in ("version", "identity", "path", "digest", "database", "mode"):
            document = deepcopy(original)
            if mode == "version": document["version"] = True
            elif mode == "identity": document["operation_id"] = str(uuid4())
            elif mode == "path": document["files"][0]["key"] = "../escape.zip"
            elif mode == "digest": document["files"][0]["sha256"] = "unknown"
            elif mode == "database": document["destination_database"] = "\ud800"
            if mode == "database":
                pin_path.write_text(json.dumps(document))
            else:
                store.write_json(pin_path, document)
            if mode == "mode": pin_path.chmod(0o644)
            with self.subTest(mode=mode), self.assertRaises(TransferError):
                storage_pins.describe_pins("incoming", "retained-owner/original.zip")
            pin_path.chmod(0o600)
        store.write_json(pin_path, original)
        with patch.object(store, "read_json", side_effect=TransferError("unavailable")):
            with self.assertRaises(TransferError):
                storage_pins.describe_pins("incoming", "retained-owner/original.zip")

    def test_scan_and_metadata_bounds_do_not_turn_unknown_retention_into_unlinked(self):
        self.pin()
        with patch.object(storage_pins, "MAX_SCAN_OPERATIONS", 0), self.assertRaises(TransferError):
            storage_pins.describe_pins("incoming", "retained-owner/original.zip")
        with patch.object(storage_pins, "MAX_SCAN_BYTES", 1), self.assertRaises(TransferError):
            storage_pins.describe_pins("incoming", "retained-owner/original.zip")


class RetainedRestoreStorageReferenceTests(PinFixtures, TestCase):
    def test_retained_database_file_is_protected_without_any_active_database_rows(self):
        self.pin()
        usage = describe_references("incoming", "retained-owner/original.zip")
        self.assertTrue(usage["checked"])
        self.assertTrue(usage["protected"])
        self.assertFalse(usage["can_quarantine"])
        self.assertEqual(usage["status"], "linked")
        self.assertEqual(usage["reference_count"], 1)
        self.assertIn("retained restore database", usage["message"])
        with self.assertRaises(StorageReferenceError):
            assert_unreferenced("incoming", "retained-owner/original.zip")

    def test_malformed_pin_makes_usage_uncertain_and_quarantine_unavailable(self):
        _operation, pin_path = self.pin()
        pin_path.write_text("broken pin")
        usage = describe_references("incoming", "unrelated-owner/another.zip")
        self.assertFalse(usage["checked"])
        self.assertTrue(usage["protected"])
        self.assertFalse(usage["can_quarantine"])
        with self.assertRaises(StorageReferenceError):
            assert_unreferenced("incoming", "unrelated-owner/another.zip")
