"""Transfer presentation retains the reviewed action and saved-download contracts."""

from copy import deepcopy

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.dashboard.services.transfer_presentation import (
    backup_storage_summary, local_datetime, present_transfer, transfer_page_copy,
)


class AdminTransferPresentationTests(SimpleTestCase):
    operation_id = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da"

    def test_backup_page_names_the_saved_stage_and_available_next_step(self):
        for values, expected in (
            ({"status": "queued"}, "Backup queued"),
            ({"status": "running"}, "Creating your backup"),
            ({"status": "completed", "downloadable": True}, "Backup ready to download"),
            ({"status": "completed", "downloadable": False}, "Backup details"),
            ({"status": "completed", "downloadable": True, "payload_released_at": "2026-10-24T12:00:00Z"},
             "Backup ZIP deleted"),
            ({"status": "completed", "package_release_requested_at": "2026-10-24T12:00:00Z"},
             "Backup ZIP deletion pending"),
            ({"status": "failed"}, "Backup needs attention"),
            ({"status": "recovery_required"}, "Backup needs attention"),
            ({"status": "running", "recoverable": True}, "Backup needs attention"),
            ({"status": "cancelled"}, "Backup cancelled"),
        ):
            with self.subTest(values=values):
                operation = {"id": self.operation_id, "kind": "export", **values}
                original = deepcopy(operation)
                title, description = transfer_page_copy(operation)
                self.assertEqual(title, expected)
                self.assertTrue(description)
                self.assertEqual(operation, original, "Page copy must never rewrite the saved operation")

    def test_restore_page_separates_restoring_verification_and_switching(self):
        for values, context, expected in (
            ({"status": "staged"}, {"needs_destination": True}, "Prepare restore destination"),
            ({"status": "planned"}, {}, "Review database restore"),
            ({"status": "queued"}, {}, "Restore queued"),
            ({"status": "running"}, {}, "Restoring your database"),
            ({"status": "completed", "result": {"verified": True}}, {}, "Restored database ready"),
            ({"status": "completed", "result": {"verified": True}}, {"database_active": True},
             "Restored database is in use"),
            ({"status": "completed", "result": {"verified": True}}, {"switch_review": True},
             "Review database switch"),
            ({"status": "completed", "result": {"verified": False}}, {}, "Restore details"),
            ({"status": "completed", "result": {"verified": True}, "database_deleted_at": "2026-10-24T12:00:00Z"},
             {}, "Restored database removed"),
            ({"status": "completed", "database_deletion_requested_at": "2026-10-24T12:00:00Z"},
             {}, "Database removal pending"),
            ({"status": "failed"}, {}, "Restore needs attention"),
            ({"status": "running", "recoverable": True}, {}, "Restore needs attention"),
            ({"status": "cancelled"}, {}, "Restore cancelled"),
        ):
            with self.subTest(values=values, context=context):
                operation = {"id": self.operation_id, "kind": "import", "profile": "database", **values}
                original = deepcopy(operation)
                title, description = transfer_page_copy(operation, native_import=True, **context)
                self.assertEqual(title, expected)
                self.assertTrue(description)
                self.assertEqual(operation, original)

    def test_records_import_does_not_claim_a_separate_restored_database_exists(self):
        operation = {"kind": "import", "profile": "accounts", "status": "completed"}
        title, description = transfer_page_copy(operation)
        self.assertEqual(title, "Import details")
        self.assertNotIn("switch", description.lower())

    def test_journal_dates_are_localized_without_modifying_the_raw_timestamps(self):
        operation = {"created_at": "2026-10-23T12:30:00+00:00", "updated_at": "invalid-date"}
        with timezone.override("Europe/Prague"):
            presented = present_transfer(operation)
            self.assertEqual(presented["display_dates"]["created_at"].isoformat(), "2026-10-23T14:30:00+02:00")
            self.assertEqual(local_datetime("2026-01-23T12:30:00Z").isoformat(), "2026-01-23T13:30:00+01:00")
        self.assertEqual(presented["created_at"], operation["created_at"])
        self.assertIsNone(presented["display_dates"]["updated_at"])
        self.assertNotIn("display_dates", operation)
        self.assertIsNone(local_datetime(None))
        self.assertIsNone(local_datetime("2026-99-99T12:30:00Z"))

    def test_history_dates_have_readable_local_time_and_a_machine_readable_instant(self):
        with timezone.override("Europe/Prague"):
            html = render_to_string("admin/includes/transfers/workspace_operations.html", {
                "history_id": "backup-history", "history_title": "Backup tasks",
                "workspace_page_url": reverse("admin_backup_export"),
                "operations": [present_transfer({
                    "id": self.operation_id, "kind": "export", "profile": "database",
                    "status": "completed", "created_at": "2026-10-23T12:30:00+00:00",
                })],
            })
        self.assertIn('datetime="2026-10-23T14:30:00+02:00"', html)
        self.assertIn("23 Oct 2026, 14:30 CEST", html)
        self.assertIn('<th scope="col">Started</th>', html)
        for label in ("Status", "Next step"):
            self.assertIn('data-label="' + label + '"', html)

    def test_backup_exclusions_are_labelled_without_reclassifying_missing_file_warnings(self):
        warnings = [
            "Contains stored credentials. Keep this backup private.",
            "Storage area incoming is unavailable; its files are not included.",
            "Private maintenance, transfer and storage-trash journals",
            "A future warning must remain visible.",
        ]
        operation = present_transfer({
            "id": self.operation_id, "kind": "export", "status": "completed",
            "result": {"warnings": warnings},
        })
        self.assertEqual(operation["result"]["warnings"], warnings)
        self.assertEqual(operation["display_exclusions"], [warnings[2]])
        self.assertEqual(operation["display_warnings"], [warnings[0], warnings[1], warnings[3]])
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertIn("<h3>Backup notes</h3>", html)
        self.assertIn("<h3>Not included in this ZIP</h3>", html)
        self.assertNotIn("<summary>Backup notes", html)
        for warning in warnings:
            self.assertIn(warning, html)

    def test_blocked_export_retains_review_identity_without_enabling_creation(self):
        html = render_to_string("admin/includes/transfers/export_review.html", {
            "export_review": {
                "review_hash": "a" * 64,
                "blockers": ["Backup storage is too small."],
                "components": [{"label": "Boundaries", "status": "unavailable", "files_count": 0, "byte_count": 0}],
            },
            "export_selection": {"components": ["boundaries", "artifacts"]},
            "export_scope_label": "Complete database: schema and every record",
            "transfer_maintenance": {"generation": 7},
            "transfers_ready": True,
            "edit_export_url": "/admin/database/?tab=export&components=boundaries",
        })
        self.assertIn('name="action" value="export" disabled', html)
        self.assertIn('name="reviewed_hash" value="' + "a" * 64 + '"', html)
        self.assertIn('name="generation" value="7"', html)
        self.assertIn('name="components" value="boundaries"', html)
        self.assertIn('name="components" value="artifacts"', html)
        self.assertIn("transfer-badge--warning", html)
        self.assertIn("&larr; Change contents", html)

    def test_running_export_keeps_saved_operation_polling_and_refresh_contract(self):
        html = render_to_string("admin/includes/transfers/operation.html", {
            "operation": {
                "id": self.operation_id, "kind": "export", "status": "running",
                "runner_active": True, "recoverable": False, "cancellable": False,
                "progress": {"label": "Writing files", "processed_items": 3, "total_items": 10},
            },
            "transfer_history_url": "/admin/database/?tab=history",
        })
        self.assertIn('data-transfer-status-url="' + reverse("admin_data_transfer_status", args=[self.operation_id]) + '"', html)
        self.assertIn('data-operation-id="' + self.operation_id + '"', html)
        self.assertIn('data-transfer-status="running"', html)
        for attribute in ("data-transfer-progress-label", "data-transfer-progress-items", "data-transfer-progress-bytes", "data-transfer-poll-message", "data-transfer-refresh", "data-transfer-running-indicator", "data-transfer-resume", "data-transfer-last-checked"):
            self.assertIn(attribute, html)
        self.assertIn("#transfer-operation", html)
        self.assertNotIn(reverse("admin_data_transfer_download", args=[self.operation_id]), html)

    def test_waiting_and_interrupted_operations_are_distinguished_from_running_work(self):
        operation = {
            "id": self.operation_id, "kind": "export", "status": "queued",
            "runner_active": False, "recoverable": False, "cancellable": True,
        }
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertIn("waiting to start", html.lower())
        self.assertIn("Your request is saved and waiting to start.", html)
        self.assertIn('data-transfer-running-indicator aria-hidden="true"', html)
        self.assertNotIn('role="progressbar"', html, "Unknown progress must not imply a percentage")
        operation["recoverable"] = True
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertIn("<h2>This task needs attention</h2>", html)
        self.assertIn("The transfer stopped.", html)
        self.assertNotIn("data-transfer-running-indicator", html)
        self.assertIn('name="action" value="retry"', html)

    def test_activity_does_not_animate_a_recoverable_transfer_as_running(self):
        html = render_to_string("admin/includes/transfers/workspace_operations.html", {
            "history_id": "backup-history", "history_title": "Backup tasks",
            "workspace_page_url": reverse("admin_backup_export"), "operations": [{
                "id": self.operation_id, "kind": "export", "profile": "database",
                "status": "running", "recoverable": True,
            }],
        })
        self.assertIn("Needs attention", html)
        self.assertIn("Review issue", html)
        self.assertNotIn("qc-admin-spinner", html)

    def test_cancelled_and_failed_transfers_explain_the_next_step_without_a_spinner(self):
        for status, expected in (("cancelled", "Create another backup"), ("failed", "available recovery actions")):
            with self.subTest(status=status):
                html = render_to_string("admin/includes/transfers/operation.html", {
                    "operation": {"id": self.operation_id, "kind": "export", "status": status},
                    "export_page_url": reverse("admin_backup_export"),
                })
                self.assertIn(expected, html)
                self.assertNotIn("qc-admin-spinner", html)

    def test_completed_export_download_is_saved_and_released_payload_stays_unavailable(self):
        operation = {
            "id": self.operation_id, "kind": "export", "status": "completed",
            "downloadable": True, "package_bytes": 2048, "package_sha256": "b" * 64,
        }
        download_url = reverse("admin_data_transfer_download", args=[self.operation_id])
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertIn(download_url, html)
        self.assertIn("2.0", html)
        self.assertNotIn('data-transfer-status-url=', html)
        operation["payload_released_at"] = "2026-10-23T10:00:00+00:00"
        html = render_to_string("admin/includes/transfers/operation.html", {"operation": operation})
        self.assertNotIn(download_url, html)
        self.assertIn("b" * 64, html)
        summary = backup_storage_summary([{**operation, "profile": "database"}])
        history = render_to_string("admin/includes/transfers/saved_backups.html", {
            "backup_storage": summary, "prepared_backups": summary["saved_exports"],
            "export_page_url": reverse("admin_backup_export"),
        })
        self.assertNotIn(download_url, history)
        self.assertNotIn(self.operation_id, history)

    def test_completed_export_without_a_download_explains_recovery_without_promising_ready(self):
        operation = {
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "completed",
            "downloadable": False, "package_bytes": 2048,
        }
        html = render_to_string("admin/includes/transfers/operation.html", {
            "operation": operation, "backup_files_url": "/admin/database/?tab=backups",
        })
        self.assertIn("<h2>Backup ZIP unavailable</h2>", html)
        self.assertIn("This backup has no available download", html)
        self.assertNotIn("Your ZIP is ready to download", html)
        self.assertNotIn("Ready to download", html)
        self.assertNotIn(reverse("admin_data_transfer_download", args=[self.operation_id]), html)
