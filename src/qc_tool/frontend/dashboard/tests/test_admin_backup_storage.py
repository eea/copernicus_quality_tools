"""Backup-file management distinguishes saved files from live databases."""

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse

from qc_tool.frontend.dashboard.services.transfer_presentation import backup_storage_summary


class AdminBackupStorageTests(SimpleTestCase):
    operation_id = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da"

    def export(self, **changes):
        return {
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "completed",
            "package_bytes": 999999, "stored_package_bytes": 2048,
            "releasable": True, "downloadable": True, **changes,
        }

    def backups(self, operations):
        return render_to_string("admin/includes/transfers/history.html", {
            "active_tab": "backups", "recent_operations": operations,
            "backup_storage": backup_storage_summary(operations, {
                "free_bytes": 4096, "reserve_bytes": 1024,
            }),
            "database_url": "/admin/database/", "area_export_url": "/admin/database/?tab=export",
        })

    def test_storage_totals_use_current_files_and_separate_imports_released_and_pending_exports(self):
        operations = [
            self.export(),
            self.export(stored_package_bytes=4096, releasable=False),
            self.export(stored_package_bytes=0, payload_released_at="2026-10-23T10:00:00Z"),
            self.export(kind="import", stored_package_bytes=8192),
            self.export(status="failed", stored_package_bytes=16),
            self.export(stored_package_bytes=None),
        ]
        summary = backup_storage_summary(operations)
        self.assertEqual(summary["saved_export_count"], 2)
        self.assertEqual(summary["saved_export_bytes"], 6144)
        self.assertEqual(summary["reclaimable_bytes"], 2048)
        self.assertEqual(summary["retained_import_count"], 1)
        self.assertEqual(summary["retained_import_bytes"], 8192)
        self.assertEqual(summary["other_package_bytes"], 16)
        self.assertEqual(summary["unknown_size_count"], 1)

    def test_backup_list_explains_database_boundary_and_confirms_only_one_saved_file(self):
        html = self.backups([self.export(source_details={"source_database": "qc_tool_current"})])
        for text in ("Download or delete saved backups", "qc_tool_current", ">Download</a>", ">Delete</summary>", "Delete saved ZIP", "2.0",
                     "Deleting a ZIP keeps your databases and original application files"):
            self.assertIn(text, html)
        self.assertIn('name="operation_id" value="' + self.operation_id + '"', html)
        self.assertIn('name="confirmed_release" required', html)
        self.assertIn('name="return_to_backup_files" value="on"', html)
        self.assertIn(reverse("admin_data_transfer_download", args=[self.operation_id]), html)
        self.assertNotIn(">Details</a>", html)
        self.assertNotIn('id="transfer-history"', html)

    def test_missing_or_unsafe_export_file_is_not_downloadable_or_counted_as_reclaimable(self):
        for size in (None, 0):
            with self.subTest(size=size):
                operation = self.export(stored_package_bytes=size)
                summary = backup_storage_summary([operation])
                self.assertEqual(summary["reclaimable_bytes"], 0)
                self.assertEqual(summary["saved_export_count"], 0)
                html = self.backups([operation])
                self.assertNotIn(reverse("admin_data_transfer_download", args=[self.operation_id]), html)
                self.assertIn("Not recorded in this export", html)

    def test_import_recovery_packages_have_no_delete_control(self):
        html = self.backups([self.export(kind="import")])
        self.assertNotIn('value="release_package"', html)
        self.assertIn("kept for restore and recovery", html)

    def test_operation_describes_export_as_saved_zip_and_deletion_preserves_database(self):
        operation = self.export()
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertIn("Restoring the ZIP later creates a separate database for review", html)
        self.assertIn("Your databases, original files, transfer history and checksum are kept", html)
        operation["payload_released_at"] = "2026-10-23T10:00:00Z"
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertIn("Saved backup ZIP deleted", html)
        self.assertIn("No database or application files were deleted", html)
