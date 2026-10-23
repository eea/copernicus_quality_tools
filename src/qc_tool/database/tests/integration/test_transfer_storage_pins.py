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
from qc_tool.database.transfers import storage_pins, store
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
