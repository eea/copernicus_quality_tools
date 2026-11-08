"""Upgrade selection never mistakes migrated bytes for the original archive."""

from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from qc_tool.database.transfers import control
from qc_tool.database.transfers.contracts import digest
from qc_tool.database.transfers.errors import TransferError


class UpgradeSnapshotSafetyTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch.object(control.selection, "database_scope", return_value=nullcontext()))
        self.schema = self.enterContext(patch.object(control, "SchemaInitializer"))
        self.history = self.enterContext(patch("qc_tool.database.migration_engine.migration_status", return_value={"state": "legacy"}))
        self.rows = self.enterContext(patch.object(control, "snapshot_current_application", return_value={"records": []}))
        self.artifacts = self.enterContext(patch.object(control, "collect_artifacts", return_value=SimpleNamespace(
            sources=[], directories=[], storage={}, warnings=[], external_requirements=[])))

    def test_destination_never_uses_legacy_source_exception(self):
        self.schema.return_value.check.side_effect = CommandError("missing history")
        with patch("qc_tool.database.migration_engine.inspect_source") as source:
            with self.assertRaisesMessage(TransferError, "installed models"):
                control._application_snapshot("candidate")
        source.assert_not_called()
        self.rows.assert_not_called()

    def test_source_exception_requires_exact_predecessor_and_current_orm_shape(self):
        self.schema.return_value.check.side_effect = [CommandError("missing history"), None]
        with patch("qc_tool.database.migration_engine.inspect_source", return_value={"state": "ready"}) as source:
            result = control._application_snapshot("original", allow_legacy=True)
        source.assert_called_once()
        self.assertEqual(result["schema_mode"], "legacy")
        self.assertEqual(self.schema.call_args.kwargs, {"require_history": False})

    def test_unknown_legacy_drift_cannot_reach_record_or_file_queries(self):
        self.schema.return_value.check.side_effect = CommandError("schema drift")
        with patch("qc_tool.database.migration_engine.inspect_source", return_value={"state": "incompatible"}):
            with self.assertRaisesMessage(TransferError, "supported migration source"):
                control._application_snapshot("original", allow_legacy=True)
        self.rows.assert_not_called()

    def test_exact_historical_contract_does_not_authorize_incompatible_current_orm(self):
        self.schema.return_value.check.side_effect = [CommandError("missing history"), CommandError("new columns")]
        with patch("qc_tool.database.migration_engine.inspect_source", return_value={"state": "ready"}):
            with self.assertRaisesMessage(TransferError, "offline upgrade"):
                control._application_snapshot("original", allow_legacy=True)
        self.rows.assert_not_called()

    def test_current_managed_source_preserves_existing_snapshot_contract(self):
        self.schema.return_value.check.return_value = {"state": "ready"}
        with patch("qc_tool.database.migration_engine.inspect_source") as source:
            result = control._application_snapshot("current", allow_legacy=True)
        self.assertNotIn("schema_mode", result)
        source.assert_not_called()

    def test_verified_pending_source_uses_all_storage_without_current_model_queries(self):
        self.schema.return_value.check.side_effect = CommandError("pending schema")
        self.history.return_value = {"state": "pending"}
        inventory = SimpleNamespace(warnings=["historical file unavailable"])
        with patch("qc_tool.database.transfers.recovery_files.snapshot", return_value=(inventory, [1, 2], "all-roots", 50)), \
                patch("qc_tool.database.transfers.recovery_files.storage_identity", return_value={"work": "/original/jobs"}):
            result = control._application_snapshot("older-managed", allow_legacy=True)
        self.assertEqual(result, {"fingerprint": digest({"content": "all-roots", "roots": {"work": "/original/jobs"}}), "files_count": 2,
                                  "warnings": inventory.warnings, "schema_mode": "pending"})
        self.rows.assert_not_called()

    def test_pending_source_keeps_existing_global_warnings_without_typed_record_contract(self):
        self.schema.return_value.check.side_effect = CommandError("pending schema")
        self.history.return_value = {"state": "pending"}
        self.artifacts.return_value.warnings = ["existing boundary configuration warning"]
        inventory = SimpleNamespace(warnings=["storage area unavailable"])
        with patch("qc_tool.database.transfers.recovery_files.snapshot", return_value=(inventory, [], "all-roots", 0)):
            result = control._application_snapshot("older-managed", allow_legacy=True)
        self.assertEqual(result["warnings"], ["storage area unavailable", "existing boundary configuration warning"])
        self.artifacts.assert_called_once_with({"profile": "application", "accounts": [], "records": {}}, include_files=True)
        self.rows.assert_not_called()


class UpgradeSelectionReceiptTests(SimpleTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.state = {"active": "original", "revision": 4}
        self.operation = {"id": "upgrade", "package_sha256": "a" * 64, "upgrade": {"target_release": "3.0.1"}}
        self.enterContext(patch.object(control.selection, "read_state", return_value=self.state))
        self.enterContext(patch.object(control, "_completed", return_value=(self.operation, "candidate")))
        self.enterContext(patch.object(control, "_receipt_path", return_value=self.directory / "absent.json"))
        self.files = self.enterContext(patch.object(control, "_application_snapshot", return_value={"fingerprint": "files", "files_count": 1, "warnings": []}))
        self.enterContext(patch.object(control, "_native_snapshot", return_value={"review_hash": "native", "oid": 42}))
        self.enterContext(patch.object(control, "_administrator", return_value={"username": "operator"}))
        self.original = self.enterContext(patch.object(control, "_verify_first_restore"))

    def test_upgraded_candidate_requires_upgrade_evidence_instead_of_original_sql_equality(self):
        with patch("qc_tool.database.upgrades.service.verify_candidate", return_value={"verified": True}) as verify:
            public, evidence = control._preview("upgrade", SimpleNamespace())
        verify.assert_called_once_with(self.operation)
        self.original.assert_not_called()
        self.assertTrue(public["can_apply"])
        self.assertEqual(evidence["operation"], self.operation)
        self.assertEqual(self.files.call_args_list[0].args, ("candidate",))
        self.assertEqual(self.files.call_args_list[1].kwargs, {"allow_legacy": True})

    def test_bad_upgrade_receipt_blocks_selection_before_orm_or_file_access(self):
        with patch("qc_tool.database.upgrades.service.verify_candidate", side_effect=TransferError("candidate changed")):
            with self.assertRaisesMessage(TransferError, "candidate changed"):
                control._preview("upgrade", SimpleNamespace())
        self.files.assert_not_called()
        self.original.assert_not_called()

    def test_plain_restore_still_requires_exact_archive_verification(self):
        self.operation.pop("upgrade")
        facade = SimpleNamespace(_verified=lambda operation: "archive")
        with patch.object(control, "_service", return_value=facade):
            public, _evidence = control._preview("upgrade", SimpleNamespace())
        self.original.assert_called_once_with(self.operation, "candidate", "archive")
        self.assertTrue(public["can_apply"])

    def test_previously_approved_upgraded_copy_is_reviewed_against_current_contents(self):
        with patch.object(control, "_selection_candidate", return_value=({"oid": 42}, self.operation)), \
                patch.object(control, "_isolate"), \
                patch("qc_tool.database.upgrades.service.verify_candidate") as initial:
            current, _evidence = control._selection_preview("candidate", SimpleNamespace(), self.state, self.operation)
        self.assertTrue(current["can_apply"])
        initial.assert_not_called()
        self.assertEqual(self.files.call_count, 2)


class LegacyRollbackSafetyTests(SimpleTestCase):
    def test_django_disposable_database_override_does_not_create_a_deployment_alias(self):
        with patch.object(control, "_service", return_value=SimpleNamespace(_authorize=lambda actor: None)), \
                patch.object(control.selection, "read_state", return_value={"active": "configured", "revision": 0}), \
                patch.object(control.selection, "current_database", return_value="test_configured"), \
                patch.object(control.selection, "configured_connection", return_value={"NAME": "configured"}), \
                patch.object(control.selection, "alias_for_database") as alias, \
                patch.object(control, "connection", SimpleNamespace(vendor="postgresql", settings_dict={"NAME": "test_configured"})), \
                patch.object(control, "connections", {"default": object()}), \
                patch.object(control, "SchemaInitializer") as schema:
            control.validate_resume(SimpleNamespace())
        alias.assert_not_called()
        schema.return_value.check.assert_called_once()

    def test_unselected_models_only_source_cannot_reopen_before_candidate_upgrade(self):
        with patch.object(control, "_service", return_value=SimpleNamespace(_authorize=lambda actor: None)), \
                patch.object(control.selection, "read_state", return_value={"active": "source", "revision": 0}), \
                patch.object(control.selection, "alias_for_database", return_value="default"), \
                patch.object(control, "connections", {"default": object()}), \
                patch.object(control, "SchemaInitializer") as schema:
            schema.return_value.check.side_effect = CommandError("missing migration history")
            with self.assertRaisesMessage(TransferError, "Keep maintenance on"):
                control.validate_resume(SimpleNamespace())
        schema.return_value.check.assert_called_once()

    def test_managed_image_explains_offline_recovery_for_models_only_previous_database(self):
        state = {"previous": "original", "maintenance_generation": 7,
                 "activation": {"source_native": {"oid": 42},
                                "source_files": {"fingerprint": "original", "schema_mode": "legacy"}}}
        with patch.object(control, "read_status", return_value={"enabled": True, "generation": 7}):
            blockers = control._rollback_blockers(state)
        self.assertEqual(len(blockers), 1)
        self.assertIn("previous pinned application images", blockers[0])
        self.assertIn("offline recovery", blockers[0])

    def test_ordinary_compatible_switch_keeps_existing_quick_recovery(self):
        state = {"previous": "original", "maintenance_generation": 7,
                 "activation": {"source_native": {"oid": 42}, "source_files": {"fingerprint": "original"}}}
        with patch.object(control, "read_status", return_value={"enabled": True, "generation": 7}):
            self.assertEqual(control._rollback_blockers(state), [])
