"""Canonical run and publication evidence survives the complete transfer workflow."""

import hashlib
import json

from django.test import TestCase

from qc_tool.database.tests.integration import test_transfer_application as fixture
from qc_tool.database.transfers import service
from qc_tool.database.transfers.archive import inspect_archive, write_archive
from qc_tool.database.transfers.artifacts import _validate_package_artifacts, collect_artifacts
from qc_tool.database.transfers.records import export_records
from qc_tool.frontend.dashboard.services.submissions.artifacts import open_submission_file
from qc_tool.jobs import create_job_paths, record_job_context, resolve_job_paths


class CanonicalPublicationTransferTests(TestCase):
    setUp = fixture.ApplicationTransferIntegrationTests.setUp
    configuration = fixture.ApplicationTransferIntegrationTests.configuration
    prepare_import = fixture.ApplicationTransferIntegrationTests.prepare_import
    assert_restored_records = fixture.ApplicationTransferIntegrationTests.assert_restored_records

    def make_graph(self):
        fixture.ApplicationTransferIntegrationTests.make_graph(
            self, write_job_artifacts=self.write_job_artifacts,
        )

    def write_job_artifacts(self, job):
        paths = create_job_paths(self.source_config["work_dir"], job.pk)
        paths.specification_path("transfer-product.json").write_bytes(self.specification)
        paths.result_path.write_text(json.dumps({"report_filename": "report.pdf"}))
        paths.report_path("report.pdf").write_bytes(b"original canonical report")
        (paths.output_dir / "attachment.txt").write_bytes(b"original canonical attachment")
        paths.worker_log_path.write_bytes(b"private diagnostic")
        record_job_context(paths, specification_filename="transfer-product.json",
                           specification_sha256=hashlib.sha256(self.specification).hexdigest())

    def test_service_roundtrip_preserves_graph_exact_manifest_and_nested_downloads(self):
        operation = self.prepare_import()
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        restored = self.assert_restored_records()
        directory = self.target_config["submission_dir"] / restored.artifact_key
        self.assertEqual((directory / "submission-manifest.json").read_bytes(), self.original_manifest)
        for name, expected in (("outputs/attachment.txt", b"original canonical attachment"),
                               ("reports/report.pdf", b"original canonical report"),
                               ("specification/transfer-product.json", self.specification)):
            with self.subTest(name=name), open_submission_file(restored, name) as stream:
                self.assertEqual(stream.read(), expected)
        paths = resolve_job_paths(self.target_config["work_dir"], restored.job_id)
        self.assertFalse(paths.legacy)
        self.assertFalse((directory / "logs").exists())
        self.assertEqual(paths.specification_path("transfer-product.json").read_bytes(), self.specification)

    def test_complete_portable_contract_accepts_canonical_publication_output_roles(self):
        payload = export_records("application")
        inventory = collect_artifacts(payload)
        package = self.root / "complete-canonical.zip"
        write_archive(package, {}, payload, inventory.sources, directories=inventory.directories,
                      storage={"boundaries": inventory.storage["boundaries"]})
        _validate_package_artifacts(inspect_archive(package))
