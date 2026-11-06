"""Separated storage refuses missing/wrong mounts before application writes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qc_tool.storage import guard


class StorageLayoutGuardTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-layout-guard-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.data = self.root / "data"
        self.environment = {
            "QC_TOOL_DATA_ROOT": str(self.data),
            "QC_TOOL_STORAGE_ROLE": "frontend",
            "QC_TOOL_SHARED_STATE_DIR": str(self.root / "state/shared"),
            "QC_TOOL_FRONTEND_STATE_DIR": str(self.root / "private/frontend"),
            "QC_TOOL_SCRATCH_DIR": str(self.root / "scratch/worker"),
            "QC_TOOL_LOG_DIR": str(self.root / "logs/frontend"),
            "QC_TOOL_PERSISTENT_STORAGE_ROOT": str(self.data),
            "QC_TOOL_PERSISTENT_STORAGE_ID": "separated-fixture-01",
            "QC_TOOL_REQUIRE_MOUNTS": "no",
        }
        # Provision fixtures as an operator would, including both role roots.
        for role in ("frontend", "worker"):
            for path, _writable in guard.layout_roots({**self.environment, "QC_TOOL_STORAGE_ROLE": role})[1].values():
                path.mkdir(parents=True, exist_ok=True)
                marker = path / guard.MARKER_NAME
                marker.write_text(self.environment["QC_TOOL_PERSISTENT_STORAGE_ID"] + "\n")
                marker.chmod(0o644)
                (path / "retained.bin").write_bytes(b"retained original\x00")

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.lstat().st_mode,
                path.read_bytes() if path.is_file() and not path.is_symlink() else None)
                for path in self.root.rglob("*")}

    def test_roles_require_only_their_owned_mounts(self):
        _, frontend = guard.layout_roots(self.environment)
        _, worker = guard.layout_roots({**self.environment, "QC_TOOL_STORAGE_ROLE": "worker"})
        self.assertEqual(set(frontend), {"incoming", "boundaries", "specifications", "jobs",
                                        "shared-state", "logs", "submissions", "frontend-state"})
        self.assertEqual(set(worker), {"incoming", "boundaries", "specifications", "jobs",
                                      "shared-state", "logs", "scratch"})
        self.assertEqual({name for name, (_path, writable) in worker.items() if not writable},
                         {"incoming", "boundaries", "specifications"})
        self.assertTrue(all(writable for _path, writable in frontend.values()))
        (self.root / "private/frontend/retained.bin").unlink()
        (self.root / "private/frontend" / guard.MARKER_NAME).unlink()
        (self.root / "private/frontend").rmdir()
        self.assertEqual(guard.check_storage({**self.environment, "QC_TOOL_STORAGE_ROLE": "worker"}), self.data)
        with self.assertRaises(guard.StorageConfigurationError):
            guard.check_storage(self.environment)

    def test_disabled_submissions_are_optional_for_service_provider(self):
        environment = {**self.environment, "SUBMISSION_DIR": ""}
        self.assertNotIn("submissions", guard.layout_roots(environment)[1])
        self.assertEqual(guard.check_storage(environment), self.data)

    def test_layout_check_is_read_only_and_identity_is_opt_in(self):
        before = self.snapshot()
        self.assertEqual(guard.check_storage(self.environment), self.data)
        self.assertEqual(guard.check_layout({**self.environment, "QC_TOOL_PERSISTENT_STORAGE_ID": ""}), self.data)
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(guard.StorageConfigurationError):
            guard.check_storage({**self.environment, "QC_TOOL_PERSISTENT_STORAGE_ID": ""})

    def test_missing_role_root_is_never_created(self):
        missing = self.root / "absent/state"
        environment = {**self.environment, "QC_TOOL_SHARED_STATE_DIR": str(missing)}
        before = self.snapshot()
        with self.assertRaises(guard.StorageConfigurationError):
            guard.check_storage(environment)
        self.assertFalse(missing.parent.exists())
        self.assertEqual(self.snapshot(), before)

    def test_each_mount_marker_is_required_even_when_jobs_marker_is_valid(self):
        roots = guard.layout_roots(self.environment)[1]
        for name, (path, _writable) in roots.items():
            with self.subTest(mount=name):
                marker = path / guard.MARKER_NAME
                original = marker.read_bytes()
                marker.write_text("another-mounted-storage\n")
                with self.assertRaisesRegex(guard.StorageConfigurationError, "does not match"):
                    guard.check_storage(self.environment)
                self.assertEqual(marker.read_text(), "another-mounted-storage\n")
                marker.unlink()
                with self.assertRaises(guard.StorageConfigurationError):
                    guard.check_storage(self.environment)
                self.assertFalse(marker.exists())
                marker.write_bytes(original)
                marker.chmod(0o644)
        self.assertEqual(guard.check_storage(self.environment), self.data)

    def test_parent_marker_cannot_substitute_for_individual_mount_markers(self):
        marker = self.data / guard.MARKER_NAME
        marker.write_text(self.environment["QC_TOOL_PERSISTENT_STORAGE_ID"] + "\n")
        (self.data / "incoming" / guard.MARKER_NAME).unlink()
        with self.assertRaises(guard.StorageConfigurationError):
            guard.check_storage(self.environment)
        self.assertFalse((self.data / "incoming" / guard.MARKER_NAME).exists())

    def test_symlink_mount_and_symlink_ancestor_are_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root / "private", target_is_directory=True)
        for value in (str(alias / "frontend"), str(self.root / "linked-frontend")):
            if value.endswith("linked-frontend"):
                Path(value).symlink_to(self.root / "private/frontend", target_is_directory=True)
            with self.subTest(path=value), self.assertRaises(guard.StorageConfigurationError):
                guard.check_storage({**self.environment, "QC_TOOL_FRONTEND_STATE_DIR": value})

    def test_overlapping_private_and_jobs_roots_are_refused(self):
        for value in (str(self.data / "jobs"), str(self.data / "jobs/private"), str(self.data)):
            with self.subTest(path=value), self.assertRaisesRegex(guard.StorageConfigurationError, "overlap"):
                guard.check_layout({**self.environment, "QC_TOOL_FRONTEND_STATE_DIR": value})

    def test_required_mountpoints_cannot_be_replaced_by_plain_directories(self):
        environment = {**self.environment, "QC_TOOL_REQUIRE_MOUNTS": "yes"}
        before = self.snapshot()
        with patch("qc_tool.storage.guard.os.path.ismount", return_value=False):
            with self.assertRaisesRegex(guard.StorageConfigurationError, "not mounted"):
                guard.check_storage(environment)
        self.assertEqual(self.snapshot(), before)
        expected = {path for path, _writable in guard.layout_roots(environment)[1].values()}
        with patch("qc_tool.storage.guard.os.path.ismount", return_value=True) as ismount:
            self.assertEqual(guard.check_storage(environment), self.data)
        self.assertEqual({call.args[0] for call in ismount.call_args_list}, expected)

    def test_private_namespaces_and_browser_root_cannot_be_retargeted_unsafely(self):
        private = self.root / "private/frontend"
        before = self.snapshot()
        invalid = (
            {"QC_TOOL_TRANSFER_DIR": str(private / "backups"), "QC_TOOL_BACKUPS_DIR": str(private / "backups")},
            {"S3_CREDENTIALS_DIR": str(private / "upload-staging")},
            {"FRONTEND_DB_PATH": str(self.data / "jobs/database.sqlite3")},
            {"FRONTEND_DB_PATH": str(private / "static/database.sqlite3")},
            {"FRONTEND_DB_PATH": str(private / "backups/database.sqlite3")},
            {"QC_TOOL_PERSISTENT_STORAGE_ROOT": str(self.root)},
        )
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(guard.StorageConfigurationError):
                guard.check_storage({**self.environment, **override})
        self.assertEqual(self.snapshot(), before)

    def test_worker_probe_never_writes_read_only_inputs(self):
        environment = {**self.environment, "QC_TOOL_STORAGE_ROLE": "worker"}
        before = self.snapshot()
        with patch("qc_tool.storage.guard._probe_at", wraps=guard._probe_at) as probe:
            guard.probe_storage(environment)
        writable = {path for path, writable in guard.layout_roots(environment)[1].values() if writable}
        self.assertEqual({call.args[0] for call in probe.call_args_list}, writable)
        self.assertEqual(self.snapshot(), before)

    def test_prepare_creates_private_upload_spool_only_after_root_validation(self):
        spool = self.root / "private/frontend/upload-staging"
        environment = {**self.environment, "QC_TOOL_UPLOAD_TEMP_DIR": str(spool)}
        guard.prepare_frontend(environment)
        self.assertTrue(spool.is_dir())
        self.assertEqual(spool.stat().st_mode & 0o777, 0o700)
        marker = self.root / "state/shared" / guard.MARKER_NAME
        marker.write_text("wrong-storage\n")
        other = spool.parent / "must-not-create"
        with self.assertRaises(guard.StorageConfigurationError):
            guard.prepare_frontend({**environment, "QC_TOOL_UPLOAD_TEMP_DIR": str(other)})
        self.assertFalse(other.exists())

    def test_private_child_escape_and_symlink_are_refused_without_external_writes(self):
        external = self.root / "external"
        external.mkdir()
        for key in ("QC_TOOL_UPLOAD_TEMP_DIR", "QC_TOOL_TRANSFER_DIR", "QC_TOOL_BACKUPS_DIR", "S3_CREDENTIALS_DIR"):
            with self.subTest(override=key), self.assertRaises(guard.StorageConfigurationError):
                guard.prepare_frontend({**self.environment, key: str(external / key.lower())})
            self.assertEqual(list(external.iterdir()), [])
        linked = self.root / "private/frontend/linked"
        linked.symlink_to(external, target_is_directory=True)
        for value in (str(linked), str(linked / "spool")):
            with self.subTest(path=value), self.assertRaises(guard.StorageConfigurationError):
                guard.prepare_frontend({**self.environment, "QC_TOOL_UPLOAD_TEMP_DIR": value})
            self.assertEqual(list(external.iterdir()), [])
