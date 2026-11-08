"""One disposable setup for all migration administration HTTP tests."""

import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.database.upgrades import service


class MigrationAdminTestCase(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        configured = override_settings(QC_TOOL_MAINTENANCE_DIR=temporary.name + "/maintenance",
                                       QC_TOOL_TRANSFER_DIR=temporary.name + "/transfers", MAINTENANCE_MODE=False)
        configured.enable()
        self.addCleanup(configured.disable)
        self.administrator = get_user_model().objects.create_superuser(
            username="migration-administrator", password="test-password", email="admin@example.test")
        self.client.force_login(self.administrator)
        self.url = reverse("admin_migrations")
        self.backup_id = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da"
        self.operation_id = "445e90b6-af76-4ac1-bcc7-7ecfd67239cb"
        self.overview = {
            "installed_release": "3.0.0", "source_release": "3.0.0", "active_database": "qc_tool",
            "database": {"state": "legacy", "applied": [],
                         "pending": [{"app_label": "dashboard", "name": "0001_initial"}], "problems": []},
            "maintenance": {"phase": "ready", "generation": 5}, "blockers": [], "operations": [],
            "can_prepare": True, "preparation_blockers": [],
            "backups": [{"id": self.backup_id, "label": "Pre-upgrade backup", "eligible": True,
                         "created_at": "2026-11-06T12:00:00+00:00", "package_bytes": 8192,
                         "coverage": "Database and retained delivery archives", "warnings": ["One historical report is missing."],
                         "blockers": []}],
        }
        self.review = {"can_apply": True, "blockers": [], "warnings": ["Remote S3 objects require separate recovery."],
            "review_hash": "a" * 64, "generation": 5, "revision": 0,
            "source_database": "qc_tool", "source_release": "3.0.0", "target_release": "3.0.0",
            "pending": [["dashboard", "0001_initial"]], "backup_id": self.backup_id,
            "backup_sha256": "b" * 64, "storage_summary": "Retained files stay at their current paths."}
        self.operation = {"id": self.operation_id, "status": "queued", "message": "Upgrade queued.",
            "error": "", "runner_active": True, "recoverable": False, "cancellable": False,
            "maintenance_owned": True, "progress": None, "destination": {"database": "qc_tool_upgrade"},
            "upgrade": {"source_release": "3.0.0", "target_release": "3.0.0", "initializes_history": True}}
        self.status = self.mock("status", return_value=self.overview)
        self.preview = self.mock("preview", return_value=self.review)
        self.start = self.mock("start", return_value=self.operation)
        self.get_operation = self.mock("get_operation", return_value=self.operation)
        self.recover = self.mock("recover", return_value=self.operation)
        self.activation_preview = self.mock("activation_preview", return_value={
            "can_apply": True, "source_database": "qc_tool", "target_database": "qc_tool_upgrade",
            "review_hash": "c" * 64, "revision": 0, "requires_credentials": False,
            "files_count": 10, "warnings": [], "blockers": []})
        self.activate = self.mock("activate", return_value={})


    def mock(self, name, **options):
        patcher = patch.object(service, name, **options)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result
