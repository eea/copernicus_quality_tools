"""Maintenance ownership, atomic receipts and recovery on disposable databases."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import CommandError
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase, override_settings

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import service, store
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


class TransferServiceTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = override_settings(QC_TOOL_MAINTENANCE_DIR=temporary.name + "/maintenance",
                                     QC_TOOL_TRANSFER_DIR=temporary.name + "/transfers", MAINTENANCE_MODE=False)
        override.enable()
        self.addCleanup(override.disable)
        self.actor = get_user_model().objects.create_superuser("operator", "operator@example.test", "test-password")
        self.source = get_user_model().objects.create_user("portable-user", "portable@example.test", "source-password")
        self.source_key = str(self.source.pk)
        launch = patch.object(service, "_launch")
        self.launch = launch.start()
        self.addCleanup(launch.stop)
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        self.assertEqual(maintenance.advance(self.generation)["phase"], "ready")

    def export(self):
        selection = {"profile": "accounts", "user_ids": [self.source.pk]}
        preview = service.export_preview(selection, self.actor)
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.assertIsNotNone(active_operation())
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.disable(self.actor, self.generation)
        result = service.run_operation(operation["id"])
        self.assertEqual(result["status"], "completed")
        stream, metadata = service.download_operation(operation["id"], self.actor)
        with stream:
            data = stream.read()
        self.assertTrue(metadata["filename"].endswith(".zip"))
        self.assertIsNone(active_operation())
        return data

    def test_schema_preflight_exposes_actual_read_only_drift_reason(self):
        with patch.object(service.SchemaInitializer, "check", side_effect=CommandError("missing table qc_database_transfer_receipt")):
            result = service.schema_readiness()
            self.assertFalse(result["ready"])
            self.assertIn("missing table qc_database_transfer_receipt", result["message"])
            with self.assertRaisesMessage(service.TransferError, "missing table qc_database_transfer_receipt"):
                service.export_preview({"profile": "accounts", "user_ids": [self.source.pk]}, self.actor)
        self.assertEqual(TransferReceipt.objects.count(), 0)
        self.assertIsNone(active_operation())
        self.assertEqual(service.list_operations(self.actor), [])

    def test_schema_preflight_does_not_expose_database_exception_details(self):
        with patch.object(service.SchemaInitializer, "check", side_effect=DatabaseError("private connection detail")):
            result = service.schema_readiness()
        self.assertFalse(result["ready"])
        self.assertIn("connectivity", result["message"])
        self.assertNotIn("private connection detail", result["message"])

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_over_limit_preview_counts_without_loading_records_or_inspecting_files(self):
        for include_files in (False, True):
            selection = {"profile": "accounts", "user_ids": [], "include_files": include_files}
            with self.subTest(include_files=include_files), patch.object(service, "_snapshot") as snapshot:
                preview = service.export_preview(selection, self.actor)
            snapshot.assert_not_called()
            self.assertEqual(preview["counts"], {"accounts": 2})
            self.assertEqual(preview["capacity"], {"code": "record_limit", "record_count": 2, "record_limit": 1})
            self.assertEqual(preview["review_hash"], "")
            self.assertTrue(preview["blockers"])
        self.assertIsNone(active_operation())
        self.assertEqual(service.list_operations(self.actor), [])

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_forged_over_limit_export_creates_no_journal_or_runner(self):
        with self.assertRaisesMessage(service.TransferError, "record limit"):
            service.create_export({"profile": "accounts", "user_ids": []}, self.actor, "a" * 64, self.generation)
        self.launch.assert_not_called()
        self.assertIsNone(active_operation())
        self.assertEqual(service.list_operations(self.actor), [])

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=2)
    def test_export_recounts_capacity_before_queuing_a_reviewed_export(self):
        selection = {"profile": "accounts", "user_ids": []}
        preview = service.export_preview(selection, self.actor)
        self.assertEqual(preview["total_records"], 2)
        self.assertEqual(preview["record_limit"], 2)
        self.assertFalse(preview["blockers"])
        get_user_model().objects.create_user("added-after-review")
        with self.assertRaisesMessage(service.TransferError, "record limit"):
            service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.launch.assert_not_called()
        self.assertIsNone(active_operation())
        self.assertEqual(service.list_operations(self.actor), [])

    def test_never_started_import_can_be_discarded_without_a_receipt_schema(self):
        data = self.export()
        for planned in (False, True):
            operation = service.stage_import(SimpleUploadedFile("accounts.zip", data), self.actor)
            directory = store.operation_dir(operation["id"])
            (directory / "package.partial").write_bytes(b"private partial package")
            if planned:
                service.plan_import(operation["id"], self.actor, {self.source_key: self.actor.pk})
            with patch.object(TransferReceipt.objects, "filter", side_effect=DatabaseError("missing receipt table")) as receipts:
                result = service.recover_operation(operation["id"], self.actor, "cancel")
            receipts.assert_not_called()
            self.assertEqual(result["status"], "cancelled")
            self.assertIsNone(active_operation())
            self.assertFalse((directory / "package.zip").exists())
            self.assertFalse((directory / "package.partial").exists())
            self.assertTrue((directory / "operation.json").exists())

    def test_attempted_import_cannot_release_maintenance_if_receipts_are_unavailable(self):
        operation, _data = self.imported()
        with patch.object(TransferReceipt.objects, "filter", side_effect=DatabaseError("private database detail")):
            with self.assertRaisesMessage(service.TransferError, "committed receipt cannot be checked"):
                service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        self.assertEqual(store.read_operation(operation["id"])["status"], "queued")
        self.assertTrue((store.operation_dir(operation["id"]) / "package.zip").exists())

    def test_malformed_export_scope_and_import_mappings_are_controlled_errors(self):
        with self.assertRaisesMessage(service.TransferError, "supported export scope"):
            service.export_preview({"profile": [], "user_ids": []}, self.actor)
        operation = service.stage_import(SimpleUploadedFile("accounts.zip", self.export()), self.actor)
        with self.assertRaisesMessage(service.TransferError, "Account mappings must explicitly name source keys"):
            service.plan_import(operation["id"], self.actor, [])
        self.assertEqual(store.read_operation(operation["id"])["status"], "staged")
        self.assertIsNone(active_operation())

    def test_cancelled_package_unlink_is_durable_before_releasing_maintenance(self):
        operation, _data = self.imported()
        directory = store.operation_dir(operation["id"])
        with patch.object(store, "sync_directory", side_effect=OSError("Injected directory sync failure")):
            with self.assertRaisesMessage(service.TransferError, "could not be discarded durably"):
                service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        self.assertEqual(store.read_operation(operation["id"])["status"], "queued")
        self.assertFalse((directory / "package.zip").exists())
        self.assertTrue((directory / "operation.json").exists())
        self.assertEqual(service.recover_operation(operation["id"], self.actor, "cancel")["status"], "cancelled")
        self.assertIsNone(active_operation())

    def test_retry_cannot_make_unreconciled_files_cancellable(self):
        operation, _data = self.imported()
        with patch.object(service, "apply_records", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                service.run_operation(operation["id"])
        self.assertTrue(store.read_operation(operation["id"])["files_started"])
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(store.read_operation(operation["id"])["status"], "queued")
        self.assertFalse(service.get_operation(operation["id"], self.actor)["cancellable"])
        with self.assertRaisesMessage(service.TransferError, "may have published files"):
            service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertTrue((store.operation_dir(operation["id"]) / "package.zip").exists())
        self.assertEqual(active_operation()["operation_id"], operation["id"])

    def test_completed_packages_cannot_be_discarded(self):
        operation, _data = self.imported()
        service.run_operation(operation["id"])
        directory = store.operation_dir(operation["id"])
        with self.assertRaisesMessage(service.TransferError, "committed receipt"):
            service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertTrue((directory / "package.zip").exists())
        completed_exports = [row for row in service.list_operations(self.actor)
                             if row["kind"] == "export" and row["status"] == "completed"]
        self.assertEqual(len(completed_exports), 1)
        export_id = completed_exports[0]["id"]
        with self.assertRaisesMessage(service.TransferError, "Completed transfers cannot be cancelled"):
            service.recover_operation(export_id, self.actor, "cancel")
        self.assertTrue((store.operation_dir(export_id) / "package.zip").exists())

    def test_unpinned_cancelled_and_failed_operations_cannot_be_retried(self):
        operation = service.stage_import(SimpleUploadedFile("accounts.zip", self.export()), self.actor)
        service.recover_operation(operation["id"], self.actor, "cancel")
        with self.assertRaisesMessage(service.TransferError, "still owns maintenance"):
            service.recover_operation(operation["id"], self.actor, "retry")
        with self.assertRaises(service.TransferError):
            service.stage_import(SimpleUploadedFile("invalid.zip", b"not a package"), self.actor)
        failed = next(row for row in service.list_operations(self.actor) if row["status"] == "failed")
        with self.assertRaisesMessage(service.TransferError, "still owns maintenance"):
            service.recover_operation(failed["id"], self.actor, "retry")
        self.assertIsNone(active_operation())

    def test_retry_requires_the_journals_valid_pinned_generation(self):
        operation, _data = self.imported()
        for generation in (None, True, "1", self.generation + 1):
            with self.subTest(generation=generation):
                journal = store.read_operation(operation["id"])
                journal["generation"] = generation
                store.save_operation(journal)
                with self.assertRaisesMessage(service.TransferError, "still owns maintenance"):
                    service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(active_operation()["operation_id"], operation["id"])

    def imported(self):
        data = self.export()
        # Simulate the separate target identity set in this disposable fixture.
        self.source.delete()
        operation = service.stage_import(SimpleUploadedFile("package.zip", data), self.actor)
        plan = service.plan_import(operation["id"], self.actor)
        self.assertTrue(plan["can_apply"])
        operation = service.start_import(operation["id"], self.actor, plan["plan_hash"], self.generation, True)
        return operation, data

    def test_account_archive_round_trip_and_duplicate_receipt(self):
        operation, data = self.imported()
        result = service.run_operation(operation["id"])
        user = get_user_model().objects.get(username="portable-user")
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(result["result"]["created_counts"]["accounts"], 1)
        self.assertEqual(TransferReceipt.objects.count(), 1)
        self.assertIsNone(active_operation())
        self.assertTrue(maintenance.read_status()["enabled"])
        duplicate = service.stage_import(SimpleUploadedFile("same.zip", data), self.actor)
        plan = service.plan_import(duplicate["id"], self.actor, {self.source_key: user.pk})
        self.assertFalse(plan["can_apply"])
        self.assertIn("already been imported", " ".join(plan["blockers"]))

    def test_precommit_failure_rolls_back_accounts_and_retry_succeeds(self):
        operation, _data = self.imported()
        with patch.object(TransferReceipt.objects, "create", side_effect=RuntimeError("Injected receipt write failure")):
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
        self.assertFalse(get_user_model().objects.filter(username="portable-user").exists())
        self.assertFalse(TransferReceipt.objects.exists())
        self.assertIsNotNone(active_operation())
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertEqual(TransferReceipt.objects.count(), 1)

    def test_lost_postcommit_journal_update_recovers_without_duplicate_insert(self):
        operation, _data = self.imported()
        real_save = store.save_operation
        def lost_ack(value):
            if value["status"] == "completed":
                raise OSError("Injected post-commit journal failure")
            return real_save(value)
        with patch.object(store, "save_operation", side_effect=lost_ack):
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
        imported_pk = get_user_model().objects.get(username="portable-user").pk
        self.assertEqual(TransferReceipt.objects.count(), 1)
        with self.assertRaisesMessage(service.TransferError, "committed receipt"):
            service.recover_operation(operation["id"], self.actor, "cancel")
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertEqual(get_user_model().objects.get(username="portable-user").pk, imported_pk)
        self.assertEqual(TransferReceipt.objects.count(), 1)

    def test_stale_review_refuses_export_and_cancel_releases_only_pin(self):
        selection = {"profile": "accounts", "user_ids": [self.source.pk]}
        preview = service.export_preview(selection, self.actor)
        get_user_model().objects.filter(pk=self.source.pk).update(first_name="Changed after preview")
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        with self.assertRaisesMessage(service.TransferError, "changed since review"):
            service.run_operation(operation["id"])
        self.assertIsNotNone(active_operation())
        service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertIsNone(active_operation())
        self.assertTrue(maintenance.read_status()["enabled"])

    def test_commit_acknowledgement_loss_uses_receipt_and_never_cancels_commit(self):
        operation, _data = self.imported()
        atomic = transaction.atomic
        @contextmanager
        def lost_commit_reply(*args, **kwargs):
            outer = not transaction.get_connection().in_atomic_block
            with atomic(*args, **kwargs):
                yield
            if outer:
                raise OSError("Injected lost COMMIT acknowledgement")
        with patch.object(service.transaction, "atomic", side_effect=lost_commit_reply):
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
        self.assertEqual(TransferReceipt.objects.count(), 1)
        self.assertTrue(store.read_operation(operation["id"])["committed"])
        self.assertFalse(store.read_operation(operation["id"])["safe_to_cancel"])
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertEqual(TransferReceipt.objects.count(), 1)

    def test_changed_target_stops_before_any_account_is_inserted(self):
        operation, _data = self.imported()
        get_user_model().objects.filter(pk=self.actor.pk).update(first_name="Target changed")
        with self.assertRaisesMessage(service.TransferError, "target or reviewed plan changed"):
            service.run_operation(operation["id"])
        self.assertFalse(get_user_model().objects.filter(username="portable-user").exists())
        service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertIsNone(active_operation())

    def test_terminal_journal_before_pin_release_can_finish_recovery(self):
        operation, _data = self.imported()
        # BaseException simulates process death without the ordinary error handler.
        with patch.object(service, "unpin_operation", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                service.run_operation(operation["id"])
        self.assertEqual(store.read_operation(operation["id"])["status"], "completed")
        self.assertTrue(service.get_operation(operation["id"], self.actor)["maintenance_owned"])
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertIsNone(active_operation())
        self.assertEqual(TransferReceipt.objects.count(), 1)

    def test_readiness_generation_and_authority_are_required(self):
        selection = {"profile": "accounts", "user_ids": [self.source.pk]}
        with self.assertRaises(service.TransferError):
            service.export_preview(selection, self.source)
        with self.assertRaises(service.TransferError):
            service.create_export(selection, self.actor, "a" * 64, self.generation - 1)
        maintenance.disable(self.actor, self.generation)
        with self.assertRaisesMessage(service.TransferError, "wait for readiness"):
            service.export_preview(selection, self.actor)

    def test_transfer_lock_refuses_parallel_runner_and_cancellation(self):
        operation, _data = self.imported()
        with store.execution_lock():
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
            with self.assertRaises(service.TransferError):
                service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertIsNotNone(active_operation())

    def test_untrusted_archive_and_symlink_operation_are_rejected(self):
        with self.assertRaises(service.TransferError):
            service.stage_import(SimpleUploadedFile("evil.zip", b"not a ZIP"), self.actor)
        link = store.directory() / "d2b4df99-b874-4b29-a96c-a955aa813c47"
        link.symlink_to(Path(self._testMethodName))
        with self.assertRaises(service.TransferError):
            service.get_operation(link.name, self.actor)

    def test_revalidation_preserves_explicit_mappings_and_explicit_empty_resets_them(self):
        operation = service.stage_import(SimpleUploadedFile("accounts.zip", self.export()), self.actor)
        blocked = service.plan_import(operation["id"], self.actor)
        source = blocked["account_mappings"][0]
        self.assertEqual(source["email"], self.source.email)
        self.assertIn("username already exists", source["blocker"])
        mapped = service.plan_import(operation["id"], self.actor, {self.source_key: self.actor.pk})
        self.assertTrue(mapped["can_apply"])
        self.assertEqual(mapped["confirmation_text"], mapped["target_label"])
        preserved = service.plan_import(operation["id"], self.actor)
        self.assertEqual(preserved["plan_hash"], mapped["plan_hash"])
        self.assertEqual(preserved["account_mappings"][0]["target_id"], self.actor.pk)
        reset = service.plan_import(operation["id"], self.actor, {})
        self.assertFalse(reset["can_apply"])
        self.assertIsNone(reset["account_mappings"][0]["target_id"])

    def test_changed_destination_is_rejected_before_queueing_and_preserves_the_review(self):
        operation = service.stage_import(SimpleUploadedFile("accounts.zip", self.export()), self.actor)
        plan = service.plan_import(operation["id"], self.actor, {self.source_key: self.actor.pk})
        reviewed = store.read_operation(operation["id"])
        get_user_model().objects.filter(pk=self.actor.pk).update(first_name="Changed after review")
        self.launch.reset_mock()
        with self.assertRaisesMessage(service.TransferError, "The destination or package changed. Recheck the destination"):
            service.start_import(operation["id"], self.actor, plan["plan_hash"], self.generation, True)
        self.launch.assert_not_called()
        self.assertIsNone(active_operation())
        self.assertEqual(store.read_operation(operation["id"]), reviewed)
        self.assertEqual(reviewed["status"], "planned")
        self.assertEqual(reviewed["core_plan"]["mappings"], {self.source_key: self.actor.pk})

    def test_rejected_export_admission_creates_no_operation_journal(self):
        selection = {"profile": "accounts", "user_ids": [self.source.pk]}
        with self.assertRaises(service.TransferError):
            service.create_export(selection, self.actor, "a" * 64, self.generation - 1)
        self.assertEqual(service.list_operations(self.actor), [])
        maintenance.disable(self.actor, self.generation)
        with self.assertRaises(service.TransferError):
            service.create_export(selection, self.actor, "a" * 64, self.generation + 1)
        self.assertEqual(service.list_operations(self.actor), [])
        self.launch.assert_not_called()

    def test_competing_export_creates_no_extra_journal_or_pin(self):
        selection = {"profile": "accounts", "user_ids": [self.source.pk]}
        preview = service.export_preview(selection, self.actor)
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        with self.assertRaises(service.TransferError):
            service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.assertEqual([row["id"] for row in service.list_operations(self.actor)], [operation["id"]])
        self.assertEqual(active_operation()["operation_id"], operation["id"])

    def test_queued_runner_has_startup_grace_then_offers_recovery_only_when_idle(self):
        operation, _data = self.imported()
        public = service.get_operation(operation["id"], self.actor)
        self.assertFalse(public["runner_active"])
        self.assertFalse(public["recoverable"])
        stored = store.read_operation(operation["id"])
        stored["queued_at"] = (datetime.now(timezone.utc) - timedelta(seconds=11)).isoformat()
        store.save_operation(stored)
        self.assertTrue(service.get_operation(operation["id"], self.actor)["recoverable"])
        with store.execution_lock():
            public = service.get_operation(operation["id"], self.actor)
            self.assertTrue(public["runner_active"])
            self.assertFalse(public["recoverable"])
            self.assertFalse(public["cancellable"])
        self.assertTrue(service.get_operation(operation["id"], self.actor)["recoverable"])

    def test_terminal_owned_journal_can_recover_without_startup_delay(self):
        operation, _data = self.imported()
        with patch.object(service, "unpin_operation", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                service.run_operation(operation["id"])
        public = service.get_operation(operation["id"], self.actor)
        self.assertTrue(public["recoverable"])
        self.assertFalse(public["cancellable"])

    def test_operation_list_probes_execution_once_and_rejects_an_unsafe_lock(self):
        operation, _data = self.imported()
        with patch.object(store, "execution_active", wraps=store.execution_active) as probe:
            service.list_operations(self.actor)
        probe.assert_called_once_with()
        lock = store.directory() / "execution.lock"
        lock.unlink()
        lock.symlink_to(store.operation_dir(operation["id"]) / "operation.json")
        with self.assertRaisesMessage(service.TransferError, "locking is unavailable"):
            service.get_operation(operation["id"], self.actor)
        with self.assertRaisesMessage(service.TransferError, "locking is unavailable"):
            service.list_operations(self.actor)

    def test_execution_probe_never_initializes_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "absent"
            with override_settings(QC_TOOL_TRANSFER_DIR=str(path)):
                self.assertFalse(store.execution_active())
            self.assertFalse(path.exists())
