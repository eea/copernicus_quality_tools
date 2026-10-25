"""Persistent deployment checks touch only disposable, operator-like fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qc_tool.storage.guard import (
    MARKER_NAME,
    StorageConfigurationError,
    check_storage,
    probe_storage,
)


class PersistentStorageGuardTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-storage-guard-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "persistent"
        self.root.mkdir()
        self.environ = {
            "QC_TOOL_PERSISTENT_STORAGE_ROOT": str(self.root),
            "QC_TOOL_PERSISTENT_STORAGE_ID": "eea-qc-production-01",
        }
        for name, child in (("WORK_DIR", "work"), ("INCOMING_DIR", "incoming"),
                            ("BOUNDARY_DIR", "boundaries"), ("SUBMISSION_DIR", "submission")):
            path = self.root / child
            path.mkdir()
            self.environ[name] = str(path)
        self.marker = self.root / MARKER_NAME
        self.marker.write_text(self.environ["QC_TOOL_PERSISTENT_STORAGE_ID"] + "\n")
        self.marker.chmod(0o600)
        (self.root / "work" / "retained.bin").write_bytes(b"original application bytes\x00")

    def snapshot(self):
        return {str(path.relative_to(self.root)): (
            path.lstat().st_mode, path.read_bytes() if path.is_file() else None
        ) for path in self.root.rglob("*")}

    def test_valid_layout_check_is_read_only_and_returns_root(self):
        before = self.snapshot()
        self.assertEqual(check_storage(self.environ), self.root)
        self.assertEqual(self.snapshot(), before)

    def test_optional_submission_directory_and_marker_without_newline(self):
        self.environ.pop("SUBMISSION_DIR")
        self.marker.write_text(self.environ["QC_TOOL_PERSISTENT_STORAGE_ID"])
        self.assertEqual(check_storage(self.environ), self.root)

    def test_missing_root_is_not_created(self):
        absent = self.parent / "unmounted" / "persistent"
        self.environ["QC_TOOL_PERSISTENT_STORAGE_ROOT"] = str(absent)
        for name in ("WORK_DIR", "INCOMING_DIR", "BOUNDARY_DIR", "SUBMISSION_DIR"):
            self.environ[name] = str(absent / name.lower())
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.assertFalse(absent.parent.exists())

    def test_missing_required_directory_is_not_created(self):
        path = self.root / "missing" / "work"
        self.environ["WORK_DIR"] = str(path)
        with self.assertRaisesRegex(StorageConfigurationError, "WORK_DIR"):
            check_storage(self.environ)
        self.assertFalse(path.parent.exists())

    def test_marker_is_never_bootstrapped(self):
        self.marker.unlink()
        before = self.snapshot()
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.snapshot(), before)

    def test_partial_configuration_and_invalid_identities_fail(self):
        for name in ("QC_TOOL_PERSISTENT_STORAGE_ROOT", "QC_TOOL_PERSISTENT_STORAGE_ID",
                     "WORK_DIR", "INCOMING_DIR", "BOUNDARY_DIR"):
            with self.subTest(missing=name), self.assertRaises(StorageConfigurationError):
                check_storage({key: value for key, value in self.environ.items() if key != name})
        for value in ("", "../wrong", "wrong\n", "wrong name", "ééa", "a" * 129):
            with self.subTest(identity=value), self.assertRaises(StorageConfigurationError):
                check_storage({**self.environ, "QC_TOOL_PERSISTENT_STORAGE_ID": value})

    def test_absolute_nonroot_confined_paths_are_required(self):
        for value in ("/", "relative", str(self.root / ".." / "persistent")):
            with self.subTest(root=value), self.assertRaises(StorageConfigurationError):
                check_storage({**self.environ, "QC_TOOL_PERSISTENT_STORAGE_ROOT": value})
        for value in (str(self.root), str(self.parent), "relative", str(self.root / ".." / "work")):
            with self.subTest(work=value), self.assertRaises(StorageConfigurationError):
                check_storage({**self.environ, "WORK_DIR": value})

    def test_wrong_or_oversized_marker_is_unchanged(self):
        for payload in (b"different-deployment\n", b"x" * 4096, b"eea-qc-production-01\n\n"):
            self.marker.write_bytes(payload)
            with self.subTest(payload=payload[:40]), self.assertRaises(StorageConfigurationError):
                check_storage(self.environ)
            self.assertEqual(self.marker.read_bytes(), payload)

    def test_marker_symlink_hardlink_directory_fifo_and_writable_modes_are_refused(self):
        original = self.parent / "original-marker"
        self.marker.rename(original)
        self.marker.symlink_to(original)
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.marker.unlink()
        os.link(original, self.marker)
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.marker.unlink()
        self.marker.mkdir()
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.marker.rmdir()
        os.mkfifo(self.marker)
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.marker.unlink()
        self.marker.write_bytes(original.read_bytes())
        self.marker.chmod(0o666)
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        self.assertEqual(self.marker.read_bytes(), original.read_bytes())

    def test_symlink_root_ancestor_or_application_path_is_refused(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(StorageConfigurationError):
            check_storage({key: value.replace(str(self.root), str(alias))
                           for key, value in self.environ.items()})
        self.environ["WORK_DIR"] = str(alias / "work")
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)
        child = self.root / "alias"
        child.symlink_to(self.root / "work", target_is_directory=True)
        self.environ["WORK_DIR"] = str(child)
        with self.assertRaises(StorageConfigurationError):
            check_storage(self.environ)

    def test_probe_preserves_original_files_and_removes_all_its_fixtures(self):
        before = self.snapshot()
        probe_storage(self.environ)
        self.assertEqual(self.snapshot(), before)

    def test_unsupported_hardlinks_or_fsync_fail_with_cleaned_probe(self):
        before = self.snapshot()
        for operation in ("os.link", "os.fsync"):
            with self.subTest(operation=operation):
                with patch("qc_tool.storage.guard." + operation, side_effect=OSError("unsupported")):
                    with self.assertRaisesRegex(StorageConfigurationError, "filesystem probe"):
                        probe_storage(self.environ)
                self.assertEqual(self.snapshot(), before)

    def test_independent_process_lock_probe_must_report_contention(self):
        before = self.snapshot()
        with patch("qc_tool.storage.guard.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(StorageConfigurationError, "independent-process"):
                probe_storage(self.environ)
        self.assertEqual(self.snapshot(), before)

    def test_silently_ignored_permission_changes_are_refused(self):
        before = self.snapshot()
        with patch("qc_tool.storage.guard.os.fchmod", return_value=None):
            with self.assertRaisesRegex(StorageConfigurationError, "permission changes"):
                probe_storage(self.environ)
        self.assertEqual(self.snapshot(), before)

    def test_probe_refuses_wrong_storage_before_creating_scratch(self):
        self.marker.write_bytes(b"another-installation\n")
        before = self.snapshot()
        with self.assertRaisesRegex(StorageConfigurationError, "does not match"):
            probe_storage(self.environ)
        self.assertEqual(self.snapshot(), before)

    def test_probe_cleanup_failure_reports_only_its_own_temporary_directory(self):
        before = self.snapshot()
        with patch("qc_tool.storage.guard.os.rmdir", side_effect=OSError("storage unavailable")):
            with self.assertRaisesRegex(StorageConfigurationError, "private temporary directory") as failure:
                probe_storage(self.environ)
        scratch = list(self.root.glob(".qc-tool-probe-*"))
        self.assertEqual(len(scratch), 1)
        self.assertIn(str(scratch[0]), str(failure.exception))
        self.assertEqual(list(scratch[0].iterdir()), [])
        scratch[0].rmdir()
        self.assertEqual(self.snapshot(), before)

    def test_commands_do_not_import_application_or_django(self):
        result = subprocess.run(
            [sys.executable, "-c", "import json,sys; import qc_tool.storage.guard; "
             "print(json.dumps([name for name in sys.modules if name.startswith(('django', 'qc_tool.common'))]))"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        self.assertEqual(json.loads(result.stdout), [])

    def test_cli_check_is_read_only_and_probe_has_explicit_scope(self):
        before = self.snapshot()
        for action in ("check", "probe"):
            with self.subTest(action=action):
                result = subprocess.run(
                    [sys.executable, "-m", "qc_tool.storage", action],
                    env={**os.environ, **self.environ}, capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.snapshot(), before)
                if action == "probe":
                    self.assertIn("does not certify multi-host", result.stdout)
        self.marker.unlink()
        result = subprocess.run(
            [sys.executable, "-m", "qc_tool.storage", "check"],
            env={**os.environ, **self.environ}, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Persistent storage is not ready", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.marker.exists())
