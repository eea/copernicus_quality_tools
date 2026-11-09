"""Versioned run storage keeps original evidence and refuses ambiguous identity."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qc_tool import common
from qc_tool.jobs import create_job_paths, JobStorageError, read_job_context, resolve_job_paths
from qc_tool.jobs.specifications import read_specification_snapshot, snapshot_specification


JOB_UUID = "01234567-89ab-cdef-0123-456789abcdef"


class JobStoragePathsTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_original_snapshot_names_do_not_collide_with_provenance_or_result(self):
        paths = create_job_paths(self.root, JOB_UUID)
        payload = b'{ "description": "Original", "steps": [] }\n'
        snapshot_specification(paths, "job.json", payload, "job")
        self.assertEqual(paths.directory.name, JOB_UUID)
        self.assertEqual((paths.specification_dir / "job.json").read_bytes(), payload)
        self.assertEqual(read_specification_snapshot(paths, "job"), payload)
        context = read_job_context(paths)
        self.assertEqual(context["specification"], {
            "filename": "job.json", "sha256": hashlib.sha256(payload).hexdigest(),
        })
        self.assertEqual(set(p.name for p in paths.directory.iterdir()), {
            "job.json", "outputs", "reports", "specification", "logs",
        })
        paths.result_path.write_text("{}")
        with self.assertRaises(JobStorageError):
            create_job_paths(self.root, JOB_UUID, exist_ok=True)

    def test_retained_legacy_layout_is_read_without_synthesizing_provenance(self):
        directory = self.root / ("job_" + JOB_UUID.replace("-", ""))
        directory.mkdir()
        original = b'{"steps": []}\n'
        (directory / "sample.json").write_bytes(original)
        paths = resolve_job_paths(self.root, JOB_UUID)
        self.assertTrue(paths.legacy)
        self.assertEqual(read_specification_snapshot(paths, "sample"), original)
        self.assertIsNone(read_job_context(paths))
        self.assertEqual(paths.console_log_path, self.root / ("job." + JOB_UUID + ".stdout"))
        self.assertFalse((directory / "job.json").exists())

    def test_collision_missing_marker_and_symlink_are_refused(self):
        paths = create_job_paths(self.root, JOB_UUID)
        legacy = self.root / ("job_" + JOB_UUID.replace("-", ""))
        legacy.mkdir()
        with self.assertRaises(JobStorageError):
            resolve_job_paths(self.root, JOB_UUID)
        legacy.rmdir()
        paths.metadata_path.unlink()
        with self.assertRaises(JobStorageError):
            resolve_job_paths(self.root, JOB_UUID)
        paths.metadata_path.symlink_to(self.root / "elsewhere")
        with self.assertRaises(JobStorageError):
            resolve_job_paths(self.root, JOB_UUID)

    def test_absent_result_is_distinct_from_corrupt_existing_job(self):
        with patch.dict(common.CONFIG, {"work_dir": self.root}):
            with self.assertRaises(FileNotFoundError):
                common.load_job_result(JOB_UUID)
            paths = create_job_paths(self.root, JOB_UUID)
            with self.assertRaises(FileNotFoundError):
                common.load_job_result(JOB_UUID)
            paths.metadata_path.write_text("{}")
            with self.assertRaises(JobStorageError):
                common.load_job_result(JOB_UUID)

    def test_uploaded_original_filename_is_bound_to_selected_payload(self):
        paths = create_job_paths(self.root, JOB_UUID)
        source = self.root / ("a" * 64 + ".json")
        payload = b'{"steps": []}\n'
        source.write_bytes(payload)
        state = {"active": True, "digest": hashlib.sha256(payload).hexdigest(),
                 "original_filename": "EXAMPLE.JSON"}
        with (patch.dict(common.CONFIG, {"work_dir": self.root}),
              patch.object(common, "locate_product_definition", return_value=source),
              patch.object(common, "current_product_specification_state", return_value=state)):
            destination = common.copy_product_definition_to_job(JOB_UUID, "example")
            self.assertEqual(destination, paths.specification_dir / "EXAMPLE.JSON")
            self.assertEqual(destination.read_bytes(), payload)
            state["digest"] = "b" * 64
            with self.assertRaises(common.QCException):
                common.copy_product_definition_to_job(JOB_UUID, "example")
