"""Path ownership must be explicit and preserve existing deployment identities."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qc_tool import common
from qc_tool.storage.layout import layout_config, runtime_paths


JOB_UUID = "01234567-89ab-cdef-0123-456789abcdef"
COMPACT_UUID = JOB_UUID.replace("-", "")


class StorageLayoutTests(TestCase):
    def test_canonical_roots_separate_data_control_scratch_and_logs_without_writes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "absent"
            config = layout_config({"QC_TOOL_DATA_ROOT": str(root / "data")})
            paths = runtime_paths(config)
            self.assertEqual(paths.jobs_dir, root / "data/jobs")
            self.assertEqual(paths.specifications_dir, root / "data/specifications")
            self.assertEqual(paths.worker_token_path, root / "state/shared/worker.token")
            self.assertEqual(paths.maintenance_dir, root / "state/shared/maintenance")
            self.assertEqual(paths.transfer_dir, Path("/var/lib/qc_tool/data-transfer"))
            self.assertEqual(paths.scratch_dir, Path("/var/tmp/qc-tool/jobs"))
            self.assertEqual(paths.logs_dir, Path("/var/log/qc-tool"))
            self.assertFalse(root.exists())

    def test_new_jobs_have_canonical_uuid_and_nested_console_log(self):
        paths = runtime_paths(layout_config({"QC_TOOL_DATA_ROOT": "/mnt/qc-tool/data"}))
        self.assertEqual(paths.job_dir(JOB_UUID), paths.jobs_dir / JOB_UUID)
        self.assertEqual(paths.job_stdout_path(JOB_UUID), paths.jobs_dir / JOB_UUID / "logs/console.log")
        self.assertEqual(paths.job_scratch_dir(JOB_UUID), paths.scratch_dir / COMPACT_UUID)
        with self.assertRaises(ValueError):
            paths.job_dir("../outside")

    def test_explicit_environment_paths_override_canonical_defaults(self):
        config = layout_config({
            "QC_TOOL_DATA_ROOT": "/mounted/data", "WORK_DIR": "/mounted/custom-jobs",
            "QC_TOOL_SHARED_STATE_DIR": "/mounted/shared", "QC_TOOL_FRONTEND_STATE_DIR": "/private/frontend",
            "QC_TOOL_SCRATCH_DIR": "/scratch/jobs", "QC_TOOL_LOG_DIR": "/logs",
            "QC_TOOL_SPECIFICATIONS_DIR": "/mounted/specifications", "SUBMISSION_DIR": "",
        })
        paths = runtime_paths(config)
        self.assertEqual(paths.jobs_dir, Path("/mounted/custom-jobs"))
        self.assertEqual(paths.worker_token_path, Path("/mounted/shared/worker.token"))
        self.assertEqual(paths.transfer_dir, Path("/private/frontend/data-transfer"))
        self.assertEqual(paths.upload_temp_dir, Path("/private/frontend/upload-staging"))
        self.assertEqual(paths.backups_dir, Path("/private/frontend/backups"))
        self.assertEqual(paths.scratch_dir, Path("/scratch/jobs"))
        self.assertEqual(paths.logs_dir, Path("/logs"))
        self.assertEqual(paths.specifications_dir, Path("/mounted/specifications"))
        self.assertIsNone(paths.submissions_dir)

    def test_legacy_fallbacks_follow_current_config_and_never_probe_canonical_paths(self):
        config = {"work_dir": Path("/legacy/work"), "frontend_db_path": Path("/legacy/frontend/db.sqlite3")}
        paths = runtime_paths(config)
        self.assertFalse(paths.canonical)
        self.assertEqual(paths.worker_token_path, Path("/legacy/work/worker.token"))
        self.assertEqual(paths.specifications_dir, Path("/legacy/work/product_definitions"))
        self.assertEqual(paths.transfer_dir, Path("/legacy/work/data-transfer"))
        self.assertIsNone(paths.scratch_dir)
        self.assertEqual(paths.job_scratch_dir(JOB_UUID), Path("/var/tmp/qc-tool/jobs") / COMPACT_UUID)
        config["work_dir"] = Path("/another/work")
        self.assertEqual(runtime_paths(config).maintenance_dir, Path("/another/work/maintenance"))

    def test_common_compatibility_helpers_use_the_supplied_config(self):
        with patch.dict(common.CONFIG, {"data_root": None, "work_dir": Path("/isolated/work")}, clear=True):
            self.assertEqual(common.compose_job_dir(JOB_UUID), Path("/isolated/work") / JOB_UUID)
            self.assertEqual(common.uploaded_definition_root(), Path("/isolated/work/product_definitions"))
            self.assertEqual(common.compose_job_stdout_filepath(JOB_UUID), Path("/isolated/work") / JOB_UUID / "logs/console.log")

    def test_selecting_a_new_layout_does_not_discover_or_move_existing_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "legacy"
            legacy.mkdir()
            retained = legacy / ("job_" + COMPACT_UUID)
            retained.mkdir()
            (retained / "result.json").write_bytes(b"retained-original")
            paths = runtime_paths(layout_config({"QC_TOOL_DATA_ROOT": str(root / "canonical/data")}))
            self.assertFalse(paths.job_dir(JOB_UUID).exists())
            self.assertEqual((retained / "result.json").read_bytes(), b"retained-original")
