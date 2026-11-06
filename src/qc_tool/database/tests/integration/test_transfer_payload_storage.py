"""Separate private backup payloads from durable transfer/recovery journals."""

from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from qc_tool.database.transfers import service, store
from . import test_transfer_native_service as native
from . import test_transfer_service as portable


class TransferPayloadStorageTests(TransactionTestCase):
    export = portable.TransferServiceTests.export

    def setUp(self):
        portable.TransferServiceTests.setUp(self)
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.backups = self.root / "backups"
        self.enterContext(override_settings(QC_TOOL_BACKUPS_DIR=self.backups))

    def exported(self):
        data = self.export()
        operation = service.list_operations(self.actor)[0]
        return operation, data

    def test_export_payload_is_private_and_separate_from_control_journals(self):
        operation, data = self.exported()
        journal = store.operation_dir(operation["id"])
        payload = store.package_dir(operation["id"])
        self.assertEqual(payload, self.backups / operation["id"])
        self.assertEqual(store.package_path(operation["id"]).read_bytes(), data)
        self.assertTrue((journal / "operation.json").is_file())
        self.assertFalse((journal / "package.zip").exists())
        self.assertEqual(stat.S_IMODE(self.backups.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(payload.stat().st_mode), 0o700)
        self.assertNotIn("package_storage", operation)

    def test_import_uses_same_protected_payload_store_and_cannot_release_original(self):
        _exported, data = self.exported()
        operation = service.stage_import(SimpleUploadedFile("accounts.zip", data), self.actor)
        self.assertEqual(store.package_path(operation["id"]).read_bytes(), data)
        self.assertFalse((store.operation_dir(operation["id"]) / "package.zip").exists())
        plan = service.plan_import(operation["id"], self.actor, {self.source_key: self.actor.pk})
        self.assertTrue(plan["can_apply"])
        with self.assertRaises(service.TransferError):
            service.release_export_package(operation["id"], self.actor)
        self.assertEqual(store.package_path(operation["id"]).read_bytes(), data)

    def test_release_removes_completed_export_bytes_and_retains_recovery_evidence(self):
        operation, _data = self.exported()
        journal = store.operation_dir(operation["id"])
        store.write_json(journal / "files.json", {"audit": "retained"})
        (journal / "runner.log").write_bytes(b"retained runner log")
        result = service.release_export_package(operation["id"], self.actor)
        self.assertTrue(result["payload_released_at"])
        self.assertFalse(store.package_path(operation["id"]).exists())
        self.assertTrue((journal / "operation.json").is_file())
        self.assertEqual(store.read_json(journal / "files.json"), {"audit": "retained"})
        self.assertEqual((journal / "runner.log").read_bytes(), b"retained runner log")

    def test_config_change_refuses_fallback_and_keeps_audit_inventory_visible(self):
        operation, data = self.exported()
        original = store.package_path(operation["id"])
        other = self.root / "different-backup-volume"
        with override_settings(QC_TOOL_BACKUPS_DIR=other):
            with self.assertRaisesMessage(service.TransferError, "configuration changed"):
                store.package_path(operation["id"])
            listing = service.list_operations(self.actor, include_storage=True)
            self.assertEqual(listing[0]["id"], operation["id"])
            self.assertIn("operator recovery", listing[0]["storage_issue"])
        self.assertFalse(other.exists())
        self.assertEqual(original.read_bytes(), data)

    def test_legacy_operation_stays_in_its_configured_journal_directory(self):
        with override_settings(QC_TOOL_BACKUPS_DIR=""):
            operation, data = self.exported()
            original = store.package_path(operation["id"])
            self.assertEqual(original.parent, store.operation_dir(operation["id"]))
        with self.assertRaisesMessage(service.TransferError, "configuration changed"):
            store.package_path(operation["id"])
        self.assertEqual(original.read_bytes(), data)

    def test_backup_root_and_operation_symlinks_are_refused(self):
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        self.backups.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(service.TransferError):
            store.package_directory()
        self.backups.unlink()
        operation, data = self.exported()
        payload = store.package_dir(operation["id"])
        saved = self.root / "saved-payload"
        payload.rename(saved)
        payload.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(service.TransferError):
            service.download_operation(operation["id"], self.actor)
        self.assertEqual((saved / "package.zip").read_bytes(), data)

    def test_public_backup_root_permissions_are_not_silently_repaired(self):
        self.backups.mkdir(mode=0o755)
        with self.assertRaises(service.TransferError):
            store.package_directory()
        self.assertEqual(stat.S_IMODE(self.backups.stat().st_mode), 0o755)

    def test_backup_root_symlink_ancestor_cannot_create_files_outside_private_state(self):
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        alias = self.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with override_settings(QC_TOOL_BACKUPS_DIR=alias / "uncreated"):
            with self.assertRaises(service.TransferError):
                store.package_directory()
        self.assertFalse((outside / "uncreated").exists())

    def test_capacity_reports_the_payload_volume(self):
        with patch.object(service.shutil, "disk_usage", return_value=SimpleNamespace(free=1000, total=2000)) as capacity:
            result = service.backup_storage_capacity(self.actor)
        capacity.assert_called_once_with(self.backups)
        self.assertEqual(result["free_bytes"], 1000)

    def test_export_scratch_cleanup_is_confined_to_payload_child(self):
        operation, _data = self.exported()
        journal = store.operation_dir(operation["id"])
        payload = store.package_dir(operation["id"])
        (journal / "database.dump").write_bytes(b"journal evidence")
        dump = payload / "database.dump"
        dump.write_bytes(b"abandoned native staging")
        dump.chmod(0o600)
        service._discard_export_scratch(operation["id"])
        self.assertFalse(dump.exists())
        self.assertEqual((journal / "database.dump").read_bytes(), b"journal evidence")

    def test_release_refuses_a_replaced_package_symlink(self):
        operation, _data = self.exported()
        package = store.package_path(operation["id"])
        outside = self.root / "must-remain.zip"
        package.rename(outside)
        package.symlink_to(outside)
        with self.assertRaises(service.TransferError):
            service.release_export_package(operation["id"], self.actor)
        self.assertTrue(outside.is_file())
        self.assertTrue(package.is_symlink())
        self.assertTrue((store.operation_dir(operation["id"]) / "operation.json").exists())


class NativeTransferPayloadStorageTests(TransactionTestCase):
    dump = native.NativeTransferServiceTests.dump
    export = native.NativeTransferServiceTests.export

    def setUp(self):
        native.NativeTransferServiceTests.setUp(self)
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.enterContext(override_settings(QC_TOOL_BACKUPS_DIR=self.root / "backups"))

    def test_native_streaming_export_and_staged_import_use_the_payload_volume(self):
        data = self.export()
        exported = service.list_operations(self.actor)[0]
        self.assertEqual(store.package_path(exported["id"]).read_bytes(), data)
        self.assertFalse((store.operation_dir(exported["id"]) / "package.zip").exists())
        imported = service.stage_import(SimpleUploadedFile("native.zip", data), self.actor)
        self.assertEqual(store.package_path(imported["id"]).read_bytes(), data)
        self.assertFalse((store.operation_dir(imported["id"]) / "package.zip").exists())
