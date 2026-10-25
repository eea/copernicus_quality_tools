"""Progress survives browser requests without rewriting operation authority."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from qc_tool.database.transfers import progress, store


class DurableExportProgressTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=self.root / "transfers"))
        self.operation = {"id": str(uuid4()), "kind": "export", "status": "running", "updated_at": store.now()}
        self.directory = store.operation_dir(self.operation["id"], create=True)
        self.journal = self.directory / "operation.json"
        self.journal.write_bytes(b"authoritative operation fixture")

    def test_frequent_chunks_coalesce_but_phase_changes_persist(self):
        clock = [0.0]
        report = progress.Reporter(self.operation["id"], clock=lambda: clock[0])
        with patch.object(store, "write_json", wraps=store.write_json) as writes:
            report("copy_files", processed_bytes=0, total_bytes=10_000, processed_items=0, total_items=3)
            for index in range(1, 1000):
                report("copy_files", processed_bytes=index)
            self.assertEqual(writes.call_count, 1)
            self.assertEqual(progress.read(self.operation)["processed_bytes"], 0)
            clock[0] = 2.1
            report("copy_files", processed_bytes=5000)
            self.assertEqual(writes.call_count, 2)
            self.assertEqual(progress.read(self.operation)["processed_bytes"], 5000)
            report("verify_package", processed_bytes=0, total_bytes=12_000)
            self.assertEqual(writes.call_count, 3)
        current = progress.read(self.operation)
        self.assertEqual(current["phase"], "verify_package")
        self.assertIsNone(current["processed_items"])
        self.assertEqual(self.journal.read_bytes(), b"authoritative operation fixture")

    def test_status_reads_do_not_write_or_launch_work(self):
        with patch.object(store, "write_json") as writes:
            first = progress.read(self.operation)
            second = progress.read(dict(self.operation))
        self.assertEqual(first, second)
        writes.assert_not_called()
        self.assertFalse((self.directory / "progress.json").exists())

    def test_completed_or_released_journal_overrides_stale_progress(self):
        progress.Reporter(self.operation["id"])("copy_files", processed_bytes=12)
        completed = {**self.operation, "status": "completed", "package_bytes": 100}
        self.assertEqual(progress.read(completed)["phase"], "completed")
        self.assertEqual(progress.read(completed)["processed_bytes"], 100)
        completed["package_release_requested_at"] = store.now()
        self.assertEqual(progress.read(completed)["phase"], "released")

    def test_advisory_write_failure_cannot_abort_archive_preparation(self):
        report = progress.Reporter(self.operation["id"])
        with patch.object(store, "write_json", side_effect=OSError("synthetic full volume")):
            report("copy_files", processed_bytes=12)
        report("verify_package", processed_bytes=0, total_bytes=100)
        self.assertEqual(progress.read(self.operation)["phase"], "verify_package")
        self.assertEqual(self.journal.read_bytes(), b"authoritative operation fixture")

    def test_corrupt_or_untrusted_progress_falls_back_without_exposing_labels(self):
        report = progress.Reporter(self.operation["id"])
        report("copy_files", processed_bytes=12)
        path = self.directory / "progress.json"
        value = store.read_json(path)
        value["label"] = "private-source-path-and-secret"
        store.write_json(path, value)
        self.assertEqual(progress.read(self.operation)["phase"], "validating")
        self.assertNotIn("secret", str(progress.read(self.operation)))
        path.write_bytes(b"x" * (progress.MAX_PROGRESS_BYTES + 1))
        self.assertEqual(progress.read(self.operation)["phase"], "validating")

    def test_callbacks_accept_only_known_phases_and_integer_counts(self):
        report = progress.Reporter(self.operation["id"])
        for phase, count in (("private-name", 1), ("copy_files", -1), ("copy_files", True), ("copy_files", 1.5)):
            with self.subTest(phase=phase, count=count), self.assertRaises(ValueError):
                report(phase, processed_bytes=count)
