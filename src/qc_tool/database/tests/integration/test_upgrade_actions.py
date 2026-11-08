"""Migration actions explain the same recovery boundaries the service enforces."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.transfers.components import FILE_COMPONENTS
from qc_tool.database.upgrades import backups, evidence, operations, overview, service


class UpgradeRecoveryActionsTests(SimpleTestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=root / "transfers"))
        self.operation = {"id": str(uuid4()), "status": "recovery_required", "upgrade": {"source_database": "original"}}
        store.operation_dir(self.operation["id"], create=True)
        self.public = self.enterContext(patch.object(operations.transfers, "_public", side_effect=lambda operation: {
            "id": operation["id"], "status": operation["status"], "recoverable": True, "runner_active": False,
        }))

    def test_interrupted_restore_can_retry_without_repeating_uncertain_migrations(self):
        result = operations.present_operation(self.operation)
        self.assertTrue(result["can_retry"])
        self.assertTrue(result["can_abandon"])
        self.assertFalse(result["recovery_reason"])

    def test_history_initialization_uses_reviewed_source_state_not_release_labels(self):
        self.operation["upgrade"].update(source_release="3.0.0", target_release="3.0.0")
        self.assertFalse(operations.present_operation(self.operation)["upgrade"]["initializes_history"])
        self.operation["upgrade"]["source_migration"] = {"state": "pending"}
        self.assertFalse(operations.present_operation(self.operation)["upgrade"]["initializes_history"])
        self.operation["upgrade"]["source_migration"]["state"] = "legacy"
        self.assertTrue(operations.present_operation(self.operation)["upgrade"]["initializes_history"])

    def test_uncertain_migration_offers_retention_instead_of_automatic_replay(self):
        self.operation["migration_started"] = True
        result = operations.present_operation(self.operation)
        self.assertFalse(result["can_retry"])
        self.assertTrue(result["can_abandon"])
        self.assertIn("cannot be replayed safely", result["recovery_reason"])

    def test_completion_evidence_permits_verification_but_not_abandonment(self):
        self.operation["migration_started"] = True
        store.write_json(evidence.receipt_path(self.operation), {"version": 1})
        result = operations.present_operation(self.operation)
        self.assertTrue(result["can_retry"])
        self.assertFalse(result["can_abandon"])

    def test_active_runner_has_no_competing_recovery_actions(self):
        self.public.side_effect = lambda operation: {"recoverable": True, "runner_active": True}
        result = operations.present_operation(self.operation)
        self.assertFalse(result["can_retry"])
        self.assertFalse(result["can_abandon"])

    def test_unavailable_database_keeps_history_visible_without_preparation_permission(self):
        with patch.object(overview.transfers, "_authorize"), \
                patch.object(overview.selection, "read_state", return_value={"active": "unavailable", "previous": "retained"}), \
                patch.object(overview, "read_status", return_value={"enabled": True, "phase": "ready"}), \
                patch.object(overview, "inspect_migrations", side_effect=TransferError("Database inspection unavailable.")), \
                patch.object(overview.transfers, "list_operations", return_value=[self.operation]), \
                patch.object(overview.store, "read_operation", return_value=self.operation), \
                patch.object(overview, "active_operation", return_value=None):
            result = service.status(object())
        self.assertEqual(result["database"]["state"], "unavailable")
        self.assertFalse(result["can_prepare"])
        self.assertEqual(result["previous_database"], "retained")
        self.assertEqual(result["operations"][0]["id"], self.operation["id"])

    def test_empty_file_selection_is_ineligible_in_both_overview_and_backup_review(self):
        operation = {"id": self.operation["id"], "kind": "export", "profile": "database",
                     "status": "completed", "created_at": "2026-11-06T12:00:00+00:00",
                     "selection": {"include_files": True, "components": []}}
        report = {"state": "legacy", "source_release": "3.0.0", "applied": [],
                  "pending": [], "problems": []}
        with patch.object(overview.transfers, "_authorize"), \
                patch.object(overview.selection, "read_state", return_value={"active": "source"}), \
                patch.object(overview, "read_status", return_value={"enabled": True, "phase": "ready"}), \
                patch.object(overview, "inspect_migrations", return_value=report), \
                patch.object(overview.transfers, "list_operations", return_value=[operation]), \
                patch.object(overview.store, "read_operation", return_value=operation), \
                patch.object(overview, "active_operation", return_value=None):
            self.assertFalse(service.status(object())["backups"][0]["eligible"])
            with self.assertRaisesMessage(TransferError, "Create a backup including specifications"):
                backups.reviewed_backup(operation["id"])

    def test_backup_coverage_contract_distinguishes_defaults_from_explicit_partial_selection(self):
        cases = (
            ({"include_files": True, "components": None}, True),
            ({"include_files": True, "components": list(FILE_COMPONENTS)}, True),
            ({"include_files": True, "components": []}, False),
            ({"include_files": True, "components": [FILE_COMPONENTS[0]]}, False),
            ({"include_files": False, "components": list(FILE_COMPONENTS)}, False),
        )
        for selection, expected in cases:
            with self.subTest(selection=selection):
                self.assertIs(backups.full_storage_coverage(selection), expected)
