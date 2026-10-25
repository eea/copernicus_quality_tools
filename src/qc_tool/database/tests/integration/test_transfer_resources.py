"""Transfer capacity and explicit payload retention on disposable storage."""

from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings

from qc_tool.database.tests.integration import test_transfer_service as fixtures
from qc_tool.database.transfers import service, store
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


class TransferResourceTests(TransactionTestCase):
    setUp = fixtures.TransferServiceTests.setUp
    export = fixtures.TransferServiceTests.export

    def completed_export(self):
        data = self.export()
        return service.list_operations(self.actor)[0], data

    def test_missing_file_choice_defaults_to_records_only(self):
        self.assertFalse(service._selection({"profile": "application", "user_ids": []})["include_files"])

    def test_unified_selection_has_whole_database_and_explicit_components(self):
        selected = service._selection({"profile": "database", "user_ids": [],
                                       "components": ["boundaries", "postgresql_globals"]})
        self.assertEqual(selected["profile"], "database")
        self.assertTrue(selected["include_files"])
        self.assertEqual(selected["components"], ["boundaries", "postgresql_globals"])
        self.assertFalse(service._selection({"profile": "database", "user_ids": [], "components": []})["include_files"])
        for components in (["unknown"], ["boundaries", "boundaries"], "boundaries"):
            with self.subTest(components=components), self.assertRaises(service.TransferError):
                service._selection({"profile": "database", "user_ids": [], "components": components})

    def test_capacity_includes_record_metadata_and_zip_bytes_without_files(self):
        preview = service.export_preview({"profile": "accounts", "user_ids": [self.source.pk]}, self.actor)
        capacity = preview["storage_capacity"]
        self.assertEqual(capacity["file_bytes"], 0)
        self.assertGreater(capacity["records_bytes"], 0)
        self.assertGreater(capacity["estimated_package_bytes"], capacity["records_bytes"])
        self.assertEqual(capacity["required_free_bytes"],
                         capacity["estimated_package_bytes"] + capacity["reserve_bytes"])
        with override_settings(QC_TOOL_TRANSFER_ARCHIVE_LIMITS={"max_archive_bytes": 100}):
            blocked = service.export_preview({"profile": "accounts", "user_ids": [self.source.pk]}, self.actor)
        self.assertTrue(blocked["blockers"])
        self.assertEqual(service.list_operations(self.actor), [])
        self.assertIsNone(active_operation())

    def test_release_only_payload_preserves_completed_audit_and_is_idempotent(self):
        operation, _ = self.completed_export()
        directory = store.operation_dir(operation["id"])
        evidence = directory / "storage-pin.json"
        evidence.write_text("retained test evidence")
        released = service.release_export_package(operation["id"], self.actor)
        self.assertEqual(released["status"], "completed")
        self.assertTrue(released["payload_released_at"])
        self.assertFalse(released["downloadable"])
        self.assertFalse(released["releasable"])
        self.assertFalse((directory / "package.zip").exists())
        self.assertTrue((directory / "operation.json").exists())
        self.assertEqual(evidence.read_text(), "retained test evidence")
        self.assertEqual(service.release_export_package(operation["id"], self.actor)["payload_released_at"],
                         released["payload_released_at"])
        with self.assertRaisesMessage(service.TransferError, "released"):
            service.download_operation(operation["id"], self.actor)

    def test_interrupted_release_hides_download_and_can_finish(self):
        operation, _ = self.completed_export()
        with patch.object(service, "_discard_package", side_effect=service.TransferError("disk sync failed")):
            with self.assertRaisesMessage(service.TransferError, "disk sync failed"):
                service.release_export_package(operation["id"], self.actor)
        retained = service.get_operation(operation["id"], self.actor)
        self.assertTrue(retained["package_release_requested_at"])
        self.assertTrue(retained["releasable"])
        self.assertFalse(retained["downloadable"])
        self.assertTrue(service.release_export_package(operation["id"], self.actor)["payload_released_at"])

    def test_pinned_or_running_export_cannot_be_released(self):
        operation, _ = self.completed_export()
        with patch.object(service, "active_operation", return_value={"operation_id": operation["id"]}):
            with self.assertRaisesMessage(service.TransferError, "maintenance pin"):
                service.release_export_package(operation["id"], self.actor)
        with store.execution_lock():
            with self.assertRaisesMessage(service.TransferError, "Another transfer"):
                service.release_export_package(operation["id"], self.actor)
        self.assertTrue(service.get_operation(operation["id"], self.actor)["downloadable"])

    def test_import_and_incomplete_export_cannot_be_released(self):
        operation, data = self.completed_export()
        from django.core.files.uploadedfile import SimpleUploadedFile
        staged = service.stage_import(SimpleUploadedFile("records.zip", data), self.actor)
        with self.assertRaisesMessage(service.TransferError, "Only a completed export"):
            service.release_export_package(staged["id"], self.actor)
        stored = store.read_operation(operation["id"])
        stored["status"] = "recovery_required"
        store.save_operation(stored)
        with self.assertRaisesMessage(service.TransferError, "Only a completed export"):
            service.release_export_package(operation["id"], self.actor)

    def test_stage_file_uses_same_validation_and_retains_original(self):
        _operation, data = self.completed_export()
        original = store.directory().parent / "operator-package.zip"
        original.write_bytes(data)
        output = StringIO()
        call_command("data_transfer", "stage-file", str(original), actor=self.actor.username,
                     records_only=True, stdout=output)
        staged = json.loads(output.getvalue())
        self.assertEqual(staged["status"], "staged")
        self.assertFalse(staged["include_files"])
        self.assertEqual(original.read_bytes(), data)
        self.assertEqual((store.operation_dir(staged["id"]) / "package.zip").read_bytes(), data)
        self.assertIsNone(active_operation())

    def test_stage_file_checks_whole_copy_space_before_creating_operation(self):
        _operation, data = self.completed_export()
        original = store.directory().parent / "operator-package.zip"
        original.write_bytes(data)
        before = [row["id"] for row in service.list_operations(self.actor)]
        with patch.object(service, "_require_space", side_effect=service.TransferError("low space")):
            with self.assertRaisesMessage(service.TransferError, "low space"):
                service.stage_import_path(original, self.actor)
        self.assertEqual([row["id"] for row in service.list_operations(self.actor)], before)

    def test_nonadministrator_cannot_stage_or_release_packages(self):
        operation, data = self.completed_export()
        original = store.directory().parent / "operator-package.zip"
        original.write_bytes(data)
        with self.assertRaisesMessage(service.TransferError, "administrator"):
            service.stage_import_path(original, self.source)
        with self.assertRaisesMessage(service.TransferError, "administrator"):
            service.release_export_package(operation["id"], self.source)

    def test_storage_inventory_includes_backups_older_than_recent_fifty_without_reading_archives(self):
        for index in range(53):
            operation = service._new("export", self.actor, profile="accounts", status="completed",
                                     package_bytes=999999, created_at=f"2026-01-01T00:00:{index:02d}+00:00")
            (store.operation_dir(operation["id"]) / "package.zip").write_bytes(b"stored ZIP" + bytes(index))
        self.assertEqual(len(service.list_operations(self.actor)), 50)
        with patch.object(service, "open_regular", side_effect=AssertionError("ZIP payload must not be opened")):
            all_operations = service.list_operations(self.actor, limit=None, include_storage=True)
        self.assertEqual(len(all_operations), 53)
        self.assertEqual(sum(row["stored_package_bytes"] for row in all_operations), sum(10 + index for index in range(53)))
        self.assertTrue(all(row["package_bytes"] == 999999 for row in all_operations))

    def test_storage_inventory_does_not_follow_package_symlinks(self):
        operation = service._new("export", self.actor, profile="accounts", status="completed")
        retained = store.directory().parent / "outside-package"
        retained.write_bytes(b"private original bytes")
        package = store.operation_dir(operation["id"]) / "package.zip"
        package.symlink_to(retained)
        row, = service.list_operations(self.actor, limit=None, include_storage=True)
        self.assertIsNone(row["stored_package_bytes"])
        self.assertIn("unsafe", row["storage_issue"])
        self.assertEqual(retained.read_bytes(), b"private original bytes")
        package.unlink()
        row, = service.list_operations(self.actor, limit=None, include_storage=True)
        self.assertEqual(row["stored_package_bytes"], 0)

    @override_settings(QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024)
    def test_backup_capacity_reports_its_own_volume_and_is_admin_only(self):
        with patch.object(service.shutil, "disk_usage", return_value=SimpleNamespace(free=4096, total=8192)):
            self.assertEqual(service.backup_storage_capacity(self.actor), {
                "free_bytes": 4096, "total_bytes": 8192, "reserve_bytes": 1024,
            })
        with self.assertRaisesMessage(service.TransferError, "administrator"):
            service.backup_storage_capacity(self.source)
        with self.assertRaisesMessage(service.TransferError, "administrator"):
            service.list_operations(self.source, limit=None, include_storage=True)

    def test_member_limit_applies_to_metadata_in_preview(self):
        with override_settings(QC_TOOL_TRANSFER_ARCHIVE_LIMITS={"max_member_bytes": 1}):
            preview = service.export_preview({"profile": "accounts", "user_ids": [self.source.pk]}, self.actor)
        self.assertTrue(any("metadata" in message for message in preview["blockers"]))

    def seed_interrupted_scratch(self, operation):
        directory = store.operation_dir(operation["id"])
        paths = [directory / ".transfer-killed.pending", directory / "database.dump"]
        for path in paths:
            path.write_bytes(b"interrupted synthetic payload")
            path.chmod(0o600)
        return paths

    def test_export_reclaims_killed_writer_scratch_before_retry(self):
        selection = {"profile": "accounts", "user_ids": [self.source.pk]}
        preview = service.export_preview(selection, self.actor)
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        scratch = self.seed_interrupted_scratch(operation)
        result = service.run_operation(operation["id"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(all(not path.exists() for path in scratch))
        self.assertTrue((store.operation_dir(operation["id"]) / "package.zip").exists())

    def test_release_also_reclaims_interrupted_private_export_scratch(self):
        operation, _ = self.completed_export()
        scratch = self.seed_interrupted_scratch(operation)
        service.release_export_package(operation["id"], self.actor)
        self.assertTrue(all(not path.exists() for path in scratch))

    def test_scratch_cleanup_refuses_links_and_preserves_their_target(self):
        operation, _ = self.completed_export()
        directory = store.operation_dir(operation["id"])
        original = directory.parent.parent / "retained-source"
        original.write_bytes(b"retained original bytes")
        (directory / ".transfer-unsafe.pending").symlink_to(original)
        with self.assertRaisesMessage(service.TransferError, "scratch storage is unsafe"):
            service.release_export_package(operation["id"], self.actor)
        self.assertEqual(original.read_bytes(), b"retained original bytes")
        self.assertTrue((directory / "package.zip").exists())
