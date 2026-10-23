"""Admin transfers preserve history independently from transported file bytes."""

from copy import deepcopy
from contextlib import nullcontext
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from qc_tool.common import CONFIG
from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import service
from qc_tool.database.transfers.archive import inspect_archive, write_archive
from qc_tool.database.transfers.compatibility import model_contract
from qc_tool.database.transfers.records import RESOURCE_FIELDS
from qc_tool.database.tests.integration import test_transfer_application as fixtures
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.artifacts.errors import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts.inputs import open_job_input


class FileChoiceTransferTests(TestCase):
    setUp = fixtures.ApplicationTransferIntegrationTests.setUp
    configuration = fixtures.ApplicationTransferIntegrationTests.configuration
    make_graph = fixtures.ApplicationTransferIntegrationTests.make_graph

    def export_package(self, include_files):
        selection = {"profile": "application", "user_ids": [], "include_files": include_files}
        preview = service.export_preview(selection, self.actor)
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        handle, _ = service.download_operation(operation["id"], self.actor)
        with handle:
            return handle.read()

    def prepare_target(self):
        # Explicit simulation of a separate target, only inside a disposable DB.
        for model, _fields in reversed(tuple(RESOURCE_FIELDS.values())):
            model.objects.all()._raw_delete("default")
        TransferReceipt.objects.all().delete()
        CONFIG.update(self.target_config)
        self.enterContext(override_settings(MEDIA_ROOT=CONFIG["incoming_dir"]))

    def import_package(self, data, include_files):
        operation = service.stage_import(SimpleUploadedFile("records.zip", data), self.actor, include_files=include_files)
        plan = service.plan_import(operation["id"], self.actor, {str(self.actor.pk): self.actor.pk, str(self.owner.pk): self.owner.pk})
        self.assertTrue(plan["can_apply"], plan["blockers"])
        service.start_import(operation["id"], self.actor, plan["plan_hash"], self.generation, True)
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        return operation, plan

    def test_records_only_roundtrip_retains_expected_file_ids_without_copying_bytes(self):
        source = self.export_package(False)
        self.prepare_target()
        operation, plan = self.import_package(source, False)
        self.assertEqual(plan["file_references"]["included"], 0)
        self.assertTrue(Job.objects.exists())
        self.assertFalse(any(path.is_file() for name in ("incoming_dir", "submission_dir", "work_dir")
                             for path in CONFIG[name].rglob("*")))
        receipt = TransferReceipt.objects.get(operation_id=operation["id"])
        retained = receipt.summary["artifact_references"]["items"]
        self.assertTrue(retained)
        expected_ids = {item["id"] for item in retained}
        again = self.export_package(False)
        path = self.root / "reexport.zip"
        path.write_bytes(again)
        archive = inspect_archive(path)
        exported = archive.storage["references"]["items"]
        self.assertTrue(expected_ids.issubset({item["id"] for item in exported}))
        self.assertFalse(archive.entries)
        original = {item["id"]: item for item in retained}
        for item in exported:
            if item["id"] in original:
                prior = original[item["id"]]
                if prior["expected_sha256"] is not None or prior["role"] in {"delivery_input", "job_input", "specification"}:
                    self.assertEqual(item["expected_sha256"], prior["expected_sha256"])
                else:
                    self.assertIn(item["expected_sha256"], (None, prior["observed_sha256"]))

    def test_import_can_ignore_packaged_bytes_then_access_exact_zip_copied_later(self):
        data = self.export_package(True)
        self.prepare_target()
        self.import_package(data, False)
        job = Job.objects.get()
        path = CONFIG["incoming_dir"] / self.owner.username / "fixture.zip"
        self.assertFalse(path.exists())
        path.parent.mkdir()
        path.write_bytes(self.input_bytes)
        with open_job_input(job) as stream:
            self.assertEqual(stream.read(), self.input_bytes)
        path.write_bytes(b"wrong later ZIP")
        with self.assertRaises(ArtifactUnavailable):
            open_job_input(job)

    def test_missing_source_files_are_explicit_and_do_not_prevent_record_preservation(self):
        for root in (self.source_config["incoming_dir"], self.source_config["submission_dir"]):
            for path in root.rglob("*"):
                if path.is_file():
                    path.unlink()
        data = self.export_package(True)
        self.prepare_target()
        _operation, plan = self.import_package(data, True)
        self.assertGreater(plan["file_references"]["missing"], 0)
        self.assertEqual(Job.objects.count(), 1)

    def test_database_activation_snapshot_keeps_missing_history_visible(self):
        from qc_tool.database.transfers import control
        data = self.export_package(False)
        self.prepare_target()
        self.import_package(data, False)
        with patch.object(control.selection, "database_scope", return_value=nullcontext()):
            snapshot = control._application_snapshot("disposable-test-database")
        self.assertEqual(snapshot["files_count"], 0)
        self.assertTrue(snapshot["warnings"])
        self.assertTrue(Job.objects.exists())

    def test_future_schema_is_reviewable_and_original_package_stays_downloadable(self):
        path = self.root / "current.zip"
        path.write_bytes(self.export_package(False))
        archive = inspect_archive(path)
        storage = deepcopy(archive.storage)
        metadata = storage["compatibility"]
        metadata["source_release"] = "3.1.0-example"
        metadata["schema"]["models"][0]["fields"][0]["null"] = not metadata["schema"]["models"][0]["fields"][0]["null"]
        metadata["model_contract"] = model_contract("application", metadata["schema"])
        records = {**archive.records, "contract": metadata["model_contract"]}
        future = self.root / "future.zip"
        write_archive(future, {**archive.manifest, "contract": metadata["model_contract"]}, records, storage=storage)
        data = future.read_bytes()
        operation = service.stage_import(SimpleUploadedFile("future.zip", data), self.actor)
        before = Job.objects.count()
        plan = service.plan_import(operation["id"], self.actor)
        self.assertFalse(plan["can_apply"])
        self.assertEqual(plan["compatibility"]["status"], "schema-drift")
        self.assertTrue(plan["compatibility"]["changes"])
        handle, _ = service.download_operation(operation["id"], self.actor)
        with handle:
            self.assertEqual(handle.read(), data)
        self.assertEqual(Job.objects.count(), before)
