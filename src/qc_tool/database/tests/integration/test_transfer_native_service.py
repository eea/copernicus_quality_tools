"""Native backups reuse admission/recovery without live-schema or SQL receipts."""

import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import postgres, service, store
from qc_tool.database.transfers.archive import inspect_archive
from qc_tool.database.transfers.components import FILE_COMPONENTS
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


class NativeTransferServiceTests(TransactionTestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=Path(directory) / "maintenance",
            QC_TOOL_TRANSFER_DIR=Path(directory) / "transfers", MAINTENANCE_MODE=False,
            QC_TOOL_RESTORE_DATABASE="separate_restore",
        ))
        self.actor = get_user_model().objects.create_superuser("native-operator", "native@example.test", "password")
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        maintenance.advance(self.generation)
        self.original_launch = service._launch
        self.launch = self.enterContext(patch.object(service, "_launch"))
        self.enterContext(patch.object(service, "_schema_ready", side_effect=AssertionError("Native backups must survive model drift")))
        self.metadata = {
            "format": "qc-tool-postgresql", "version": 1, "created_at": "2026-10-21T12:00:00+00:00",
            "review_hash": "a" * 64, "counts": {"public.auth_user": 1, "public.extra_table": 2},
            "source_details": {"source_database": "native_source", "app_version": "3.0.0",
                               "postgresql_version": "17.6", "exported_at": "2026-10-21T12:00:00+00:00"},
        }
        self.enterContext(patch.object(postgres, "preview", return_value=self.metadata.copy()))
        self.enterContext(patch.object(postgres, "capture_stream", side_effect=self.dump))
        self.enterContext(patch.object(postgres, "inspect_native", side_effect=lambda package: package.records))
        self.target = {"database": "separate_restore", "oid": 98765}
        self.native_plan = {
            "can_apply": True, "blockers": [], "warnings": [],
            "target_label": "postgresql / separate_restore", "confirmation_text": "postgresql / separate_restore",
            "target_fingerprint": self.target, "counts": self.metadata["counts"],
        }
        self.planner = self.enterContext(patch.object(postgres, "plan_restore", return_value=self.native_plan))
        self.restorer = self.enterContext(patch.object(postgres, "restore", return_value={
            "target_label": self.native_plan["target_label"], "counts": self.metadata["counts"],
        }))
        self.verifier = self.enterContext(patch.object(postgres, "verify_restore", return_value=self.restorer.return_value))

    def dump(self, output, **kwargs):
        data = b"PGDMP synthetic native archive"
        output.write(data)
        return {**self.metadata, "dump_sha256": hashlib.sha256(data).hexdigest(), "dump_bytes": len(data)}

    def export(self):
        selection = {"profile": "database", "user_ids": []}
        preview = service.export_preview(selection, self.actor)
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        result = service.run_operation(operation["id"])
        self.assertEqual(result["status"], "completed")
        stream, _metadata = service.download_operation(operation["id"], self.actor)
        with stream:
            data = stream.read()
        self.assertIsNone(active_operation())
        return data

    def import_plan(self):
        operation = service.stage_import(SimpleUploadedFile("native.zip", self.export()), self.actor)
        plan = service.plan_import(operation["id"], self.actor)
        return operation, plan

    def queued_import(self):
        operation, plan = self.import_plan()
        return service.start_import(operation["id"], self.actor, plan["plan_hash"], self.generation, True)

    def test_full_export_ignores_model_drift_and_retains_unmanaged_inventory(self):
        self.export()
        operation = service.list_operations(self.actor)[0]
        self.assertEqual(operation["result"]["counts"], self.metadata["counts"])
        self.assertEqual(operation["source_details"], self.metadata["source_details"])
        self.assertFalse((store.operation_dir(operation["id"]) / "database.dump").exists())
        self.assertTrue(maintenance.read_status()["enabled"])
        self.assertFalse(TransferReceipt.objects.exists())

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_native_export_does_not_apply_portable_record_capacity(self):
        with patch.object(service, "_record_capacity", side_effect=AssertionError("Native SQL has no portable row cap")):
            self.export()
        self.assertEqual(service.list_operations(self.actor)[0]["result"]["counts"], self.metadata["counts"])

    def test_compressed_selected_files_export_and_stage_under_the_same_archive_limits(self):
        from qc_tool.common import CONFIG

        root = store.directory().parent / "business-files"
        configuration = {name: root / name for name in (
            "work_dir", "incoming_dir", "submission_dir", "boundary_dir")}
        for directory in configuration.values():
            directory.mkdir(parents=True)
        configuration["product_dirs"] = []
        boundary = b"original boundary feature\n" * 200_000
        files = {
            ("work_dir", "product_definitions/example.json"): b'{"original":"specification bytes"}\n',
            ("work_dir", "job_" + "a" * 32 + "/evidence.bin"): b"original QC evidence",
            ("incoming_dir", "operator/input.zip"): b"original delivery bytes",
            ("submission_dir", "published/receipt.json"): b'{"original":"publication bytes"}\n',
            ("boundary_dir", "vector/complete.gpkg"): boundary,
        }
        for (name, key), payload in files.items():
            path = configuration[name] / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.enterContext(patch.dict(CONFIG, configuration))
        limit, free, reserve = 256 * 1024, 384 * 1024, 32 * 1024
        self.enterContext(override_settings(
            QC_TOOL_TRANSFER_ARCHIVE_LIMITS={"max_archive_bytes": limit},
            QC_TOOL_TRANSFER_MIN_FREE_BYTES=reserve,
        ))
        selection = {"profile": "database", "user_ids": [], "components": list(FILE_COMPONENTS)}
        self.assertGreater(len(boundary), limit)
        self.assertGreater(len(boundary), free - reserve)
        # Only the backup volume is constrained during creation. Restore still
        # needs room for the original expanded files on their destination volume.
        with patch.object(service.shutil, "disk_usage", return_value=SimpleNamespace(free=free, total=free * 2)):
            preview = service.export_preview(selection, self.actor)
            self.assertFalse(preview["blockers"], preview["blockers"])
            self.assertEqual({row["key"] for row in preview["components"] if row["selected"]}, set(FILE_COMPONENTS))
            operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
            result = service.run_operation(operation["id"])
        self.assertEqual(result["status"], "completed")
        package = store.operation_dir(operation["id"]) / "package.zip"
        self.assertLess(package.stat().st_size, min(limit, free - reserve))
        verified = inspect_archive(package, limits=service._limits())
        self.assertEqual(verified.records["counts"], self.metadata["counts"])
        identities = {"work_dir": "work", "incoming_dir": "incoming",
                      "submission_dir": "submissions", "boundary_dir": "boundaries"}
        entries = {(entry["root"], entry["key"]): entry for entry in verified.entries}
        for (name, key), payload in files.items():
            with verified.open_artifact(entries[identities[name], key]) as stream:
                self.assertEqual(stream.read(), payload)
            self.assertEqual((configuration[name] / key).read_bytes(), payload)
        with zipfile.ZipFile(package) as archive:
            member = archive.getinfo("boundaries/vector/complete.gpkg")
            self.assertLess(member.compress_size, member.file_size)
        with package.open("rb") as stream:
            staged = service.stage_import(SimpleUploadedFile("complete.zip", stream.read()), self.actor)
        planned = service.plan_import(staged["id"], self.actor)
        self.assertTrue(staged["include_files"])
        self.assertTrue(planned["can_apply"], planned["blockers"])
        self.assertEqual(planned["counts"], self.metadata["counts"])
        self.assertIsNone(active_operation())

    def test_native_import_uses_separate_target_without_live_sql_receipts(self):
        operation = self.queued_import()
        with patch.object(TransferReceipt.objects, "filter", side_effect=AssertionError("No live receipt reads")), \
                patch.object(TransferReceipt.objects, "create", side_effect=AssertionError("No live receipt writes")):
            result = service.run_operation(operation["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["target_label"], self.native_plan["target_label"])
        self.assertEqual(self.restorer.call_args.args[1], self.target)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertIsNone(active_operation())
        self.assertTrue(maintenance.read_status()["enabled"])

    def test_occupied_destination_is_rejected_before_maintenance_is_pinned(self):
        operation, plan = self.import_plan()
        self.planner.return_value = {**self.native_plan, "can_apply": False, "blockers": ["Target is occupied"]}
        with self.assertRaisesMessage(service.TransferError, "destination or package changed"):
            service.start_import(operation["id"], self.actor, plan["plan_hash"], self.generation, True)
        self.assertIsNone(active_operation())
        self.restorer.assert_not_called()

    def test_lost_restore_acknowledgement_retains_pin_and_recovery_checks_original_target(self):
        operation = self.queued_import()

        def lose_commit_acknowledgement(*args, **kwargs):
            self.planner.return_value = {**self.native_plan, "can_apply": False, "blockers": ["Commit may have succeeded"]}
            raise service.TransferError("Connection lost; verify destination")

        self.restorer.side_effect = lose_commit_acknowledgement
        with self.assertRaises(service.TransferError):
            service.run_operation(operation["id"])
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        self.assertFalse(service.get_operation(operation["id"], self.actor)["cancellable"])
        self.restorer.side_effect = None
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertFalse(service.get_operation(operation["id"], self.actor)["cancellable"])
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertEqual(self.restorer.call_args.args[1], self.target)
        self.assertIsNone(active_operation())

    def test_uncertain_restore_cannot_be_cancelled_when_target_is_occupied(self):
        operation = self.queued_import()
        self.restorer.side_effect = service.TransferError("Lost restore acknowledgement")
        with self.assertRaises(service.TransferError):
            service.run_operation(operation["id"])
        self.planner.return_value = {**self.native_plan, "can_apply": False, "blockers": ["Occupied"]}
        with self.assertRaisesMessage(service.TransferError, "occupied or changed"):
            service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        self.assertTrue((store.operation_dir(operation["id"]) / "package.zip").exists())

    def test_failed_restore_can_be_cancelled_only_after_original_target_is_proven_empty(self):
        operation = self.queued_import()
        self.restorer.side_effect = service.TransferError("Restore transaction rolled back")
        with self.assertRaises(service.TransferError):
            service.run_operation(operation["id"])
        with patch.object(TransferReceipt.objects, "filter", side_effect=AssertionError("No live receipts")):
            result = service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(active_operation())
        self.assertFalse((store.operation_dir(operation["id"]) / "package.zip").exists())

    def test_full_database_scope_cannot_silently_become_a_user_subset(self):
        with self.assertRaises(service.TransferError):
            service.export_preview({"profile": "database", "user_ids": [self.actor.pk]}, self.actor)

    def test_stale_source_backup_cannot_complete_or_release_maintenance(self):
        selection = {"profile": "database", "user_ids": []}
        operation = service.create_export(selection, self.actor, "b" * 64, self.generation)
        with self.assertRaisesMessage(service.TransferError, "changed since review"):
            service.run_operation(operation["id"])
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        self.assertFalse((store.operation_dir(operation["id"]) / "package.zip").exists())

    def test_native_child_retains_execution_lease_after_parent_releases_it(self):
        child = None
        try:
            with store.execution_lock():
                lease = store.execution_lease_descriptor()
                self.assertIsInstance(lease, int)
                child = subprocess.Popen(
                    [sys.executable, "-c", "import sys; print('ready', flush=True); sys.stdin.read()"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, pass_fds=(lease,),
                )
                self.assertEqual(child.stdout.readline(), b"ready\n")
            self.assertIsNone(store.execution_lease_descriptor())
            self.assertTrue(store.execution_active())
            with self.assertRaisesMessage(service.TransferError, "Another transfer is running"):
                with store.execution_lock():
                    pass
            child.stdin.close()
            self.assertEqual(child.wait(timeout=10), 0)
            self.assertFalse(store.execution_active())
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                if child.stdout:
                    child.stdout.close()

    def test_failed_native_retry_launch_does_not_claim_uncertain_restore_is_cancellable(self):
        operation = self.queued_import()

        def uncertain_commit(*args, **kwargs):
            self.planner.return_value = {**self.native_plan, "can_apply": False, "blockers": ["Occupied"]}
            raise service.TransferError("Uncertain commit")

        self.restorer.side_effect = uncertain_commit
        with self.assertRaises(service.TransferError):
            service.run_operation(operation["id"])
        with patch.object(service, "_launch", self.original_launch), \
                patch.object(service.subprocess, "Popen", side_effect=OSError("No process available")):
            with self.assertRaisesMessage(service.TransferError, "runner could not start"):
                service.recover_operation(operation["id"], self.actor, "retry")
        self.assertFalse(service.get_operation(operation["id"], self.actor)["cancellable"])
        self.assertEqual(active_operation()["operation_id"], operation["id"])

    @override_settings(QC_TOOL_RESTORE_DATABASE="")
    def test_no_configured_target_is_a_pending_ui_step_without_database_creation(self):
        data = self.export()
        operation = service.stage_import(SimpleUploadedFile("native.zip", data), self.actor)
        with patch.object(postgres, "prepare_restore_target") as create:
            plan = service.plan_import(operation["id"], self.actor)
        create.assert_not_called()
        self.planner.assert_not_called()
        self.assertFalse(plan["can_apply"])
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["counts"], self.metadata["counts"])

    @override_settings(QC_TOOL_RESTORE_DATABASE="")
    def test_explicit_preparation_persists_the_server_owned_destination_and_review(self):
        data = self.export()
        operation = service.stage_import(SimpleUploadedFile("native.zip", data), self.actor)
        destination = {"database": "qc_restore_server_owned", "target_oid": 5678, "ready": True}
        with patch.object(postgres, "prepare_restore_target", return_value=destination) as create:
            result = service.prepare_restore_destination(operation["id"], self.actor)
        create.assert_called_once()
        self.assertEqual(create.call_args.args[1], operation["id"])
        self.assertEqual(result["status"], "planned")
        self.assertEqual(store.read_operation(operation["id"])["destination"], destination)
        self.assertEqual(self.planner.call_args.kwargs["destination"], destination["database"])
        self.assertTrue(result["plan"]["can_apply"])
        self.assertIsNone(active_operation())
