"""Backup creation and restoration remain separate, read-only landing pages."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.database.transfers import service
from qc_tool.frontend.dashboard.services import maintenance


class AdminBackupWorkspaceTests(TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=root / "maintenance",
            QC_TOOL_TRANSFER_DIR=root / "transfers", MAINTENANCE_MODE=False,
        ))
        self.actor = get_user_model().objects.create_superuser(
            username="backup-workspace-admin", password="test-password",
        )
        self.client.force_login(self.actor)
        self.export_url = reverse("admin_backup_export")
        self.import_url = reverse("admin_backup_import")
        self.operations = self.enterContext(patch.object(service, "list_operations", return_value=[]))
        self.enterContext(patch.object(service, "schema_readiness", return_value={"ready": True, "message": ""}))
        self.enterContext(patch.object(service, "database_availability", return_value={
            "ready": True, "message": "", "can_create_restore_database": True,
        }))
        self.enterContext(patch.object(service, "database_control_status", return_value={
            "active_database": "qc_live", "previous_database": "", "revision": 0,
        }))
        self.enterContext(patch.object(service, "backup_storage_capacity", return_value={
            "free_bytes": 4 * 1024**3, "reserve_bytes": 1024**3,
        }))

    def assert_export_page(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="components"')
        self.assertContains(response, 'value="preview_export"')
        self.assertNotContains(response, 'name="package"')
        self.assertNotContains(response, 'value="upload"')
        self.assertNotContains(response, 'href="' + self.import_url + '"')
        self.assertNotContains(response, 'aria-label="Maintenance tasks"')
        self.assertNotContains(response, 'id="database-recovery"')

    def assert_import_page(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="package"')
        self.assertContains(response, 'value="upload"')
        self.assertNotContains(response, 'name="components"')
        self.assertNotContains(response, 'value="preview_export"')
        self.assertNotContains(response, 'href="' + self.export_url + '"')
        self.assertNotContains(response, 'id="saved-backups"')
        self.assertNotContains(response, 'aria-label="Maintenance tasks"')
        self.assertNotContains(response, 'id="database-recovery"')

    def test_create_and_restore_pages_have_only_their_own_controls(self):
        self.assert_export_page(self.client.get(self.export_url))
        self.assert_import_page(self.client.get(self.import_url))

    def test_query_parameters_cannot_change_a_canonical_pages_direction(self):
        self.assert_export_page(self.client.get(self.export_url, {"tab": "import"}))
        self.assert_import_page(self.client.get(self.import_url, {"tab": "export"}))

    def test_legacy_bookmarks_open_a_single_direction(self):
        legacy = reverse("admin_data_transfer")
        for tab in ("export", "backups", "history", "activity", "transfers"):
            with self.subTest(tab=tab):
                self.assert_export_page(self.client.get(legacy, {"tab": tab}))
        self.assert_export_page(self.client.get(legacy))
        self.assert_import_page(self.client.get(legacy, {"tab": "import"}))

    def test_wrong_direction_operation_redirects_to_its_own_page(self):
        for source, destination, kind in (
            (self.export_url, self.import_url, "import"),
            (self.import_url, self.export_url, "export"),
        ):
            operation = {"id": str(uuid4()), "kind": kind, "profile": "database", "status": "completed"}
            with self.subTest(kind=kind), patch.object(service, "get_operation", return_value=operation):
                response = self.client.get(source, {"operation": operation["id"], "from": "databases"})
                self.assertEqual(response.status_code, 302)
                redirect = urlsplit(response["Location"])
                self.assertEqual(redirect.path, destination)
                self.assertEqual(parse_qs(redirect.query), {
                    "operation": [operation["id"]], "from": ["databases"],
                })

    def test_wrong_direction_post_never_reaches_a_mutation_service(self):
        with patch.object(service, "export_preview") as preview, patch.object(service, "stage_import") as stage:
            self.assertEqual(self.client.post(self.import_url, {
                "action": "preview_export", "scope": "database", "components": [],
            }).status_code, 400)
            self.assertEqual(self.client.post(self.export_url, {
                "action": "upload", "package": SimpleUploadedFile("backup.zip", b"synthetic backup"),
            }).status_code, 400)
        preview.assert_not_called()
        stage.assert_not_called()

    def test_prepared_export_older_than_fifty_other_operations_is_downloadable(self):
        recent_imports = [{
            "id": str(uuid4()), "kind": "import", "profile": "database", "status": "completed",
            "created_at": "2026-10-25T12:00:00+00:00", "downloadable": False, "stored_package_bytes": 512,
        } for _ in range(50)]
        prepared = {
            "id": str(uuid4()), "kind": "export", "profile": "accounts", "status": "completed",
            "created_at": "2026-10-20T12:00:00+00:00", "downloadable": True,
            "stored_package_bytes": 2048, "releasable": True,
        }
        missing = {**prepared, "id": str(uuid4()), "stored_package_bytes": 0}
        deleted = {**prepared, "id": str(uuid4()), "payload_released_at": "2026-10-24T12:00:00+00:00"}
        journals = [*recent_imports, prepared, missing, deleted]

        def inventory(actor, *, limit=50, include_storage=False):
            return journals if limit is None else journals[:limit]

        self.operations.side_effect = inventory
        response = self.client.get(self.export_url)

        self.assert_export_page(response)
        self.assertContains(response, 'href="' + reverse("admin_data_transfer_download", args=[prepared["id"]]) + '"')
        for operation in (missing, deleted):
            self.assertNotContains(response, 'href="' + reverse("admin_data_transfer_download", args=[operation["id"]]) + '"')
        for operation in recent_imports:
            self.assertNotContains(response, operation["id"])

    def test_restore_history_never_lists_export_operations(self):
        imported = {"id": str(uuid4()), "kind": "import", "profile": "accounts", "status": "staged"}
        exported = {"id": str(uuid4()), "kind": "export", "profile": "database", "status": "queued"}
        self.operations.return_value = [imported, exported]

        response = self.client.get(self.import_url)

        self.assert_import_page(response)
        self.assertContains(response, imported["id"])
        self.assertNotContains(response, exported["id"])

    def test_completed_exports_needing_recovery_or_cleanup_remain_in_backup_tasks(self):
        recovery = {
            "id": str(uuid4()), "kind": "export", "profile": "database", "status": "completed",
            "recoverable": True, "downloadable": False, "stored_package_bytes": 2048,
        }
        cleanup = {
            **recovery, "id": str(uuid4()), "recoverable": False, "downloadable": True,
            "package_release_requested_at": "2026-10-24T12:00:00+00:00",
        }
        self.operations.return_value = [recovery, cleanup]

        response = self.client.get(self.export_url)

        self.assert_export_page(response)
        self.assertContains(response, 'id="backup-history"')
        for operation in (recovery, cleanup):
            self.assertContains(response, 'href="{}?operation={}#transfer-operation"'.format(
                self.export_url, operation["id"],
            ))
            self.assertNotContains(response, 'href="' + reverse("admin_data_transfer_download", args=[operation["id"]]) + '"')

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_landing_get_requests_do_not_write_records_or_start_transfers(self):
        with (
            patch.object(service, "create_export") as create,
            patch.object(service, "stage_import") as stage,
            patch.object(service, "run_operation") as run,
            patch.object(maintenance, "enable") as enable,
            CaptureQueriesContext(connection) as queries,
        ):
            self.assert_export_page(self.client.get(self.export_url))
            self.assert_import_page(self.client.get(self.import_url))
        for action in (create, stage, run, enable):
            action.assert_not_called()
        self.assertEqual([
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))
        ], [])

    def test_both_pages_require_an_administrator_and_csrf_for_actions(self):
        anonymous = Client()
        staff = get_user_model().objects.create_user(username="backup-read-only-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        unauthorized = Client()
        unauthorized.force_login(staff)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.actor)
        for url, action in ((self.export_url, "preview_export"), (self.import_url, "upload")):
            with self.subTest(url=url):
                self.assertRedirects(anonymous.get(url), reverse("admin_login") + "?next=" + url,
                                     fetch_redirect_response=False)
                self.assertEqual(unauthorized.get(url).status_code, 403)
                self.assertEqual(csrf.post(url, {"action": action}).status_code, 403)
