"""Scratch isolation, active leases and debug retention on disposable files."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase

from qc_tool.worker.manager import JobdirManager
from qc_tool.worker.scratch import LEASE_FILENAME, META_FILENAME, ScratchLease, process_namespace


JOB_UUID = "01234567-89ab-cdef-0123-456789abcdef"
COMPACT_UUID = JOB_UUID.replace("-", "")


class WorkerScratchTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-scratch-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.scratch_root = self.root / "scratch"
        self.scratch_root.mkdir()
        self.scratch = self.scratch_root / COMPACT_UUID
        self.job_dir = self.root / "retained" / ("job_" + COMPACT_UUID)

    def test_scratch_is_local_and_cleanup_preserves_retained_outputs(self):
        with JobdirManager(self.job_dir, scratch_dir=self.scratch, job_uuid=JOB_UUID) as manager:
            self.assertEqual(manager.tmp_dir, self.scratch / "tmp.d")
            self.assertFalse((self.job_dir / "tmp.d").exists())
            (manager.tmp_dir / "extracted.tif").write_bytes(b"temporary")
            output = manager.output_dir / "errors.gpkg"
            output.write_bytes(b"retained output")
            metadata = json.loads((self.scratch / META_FILENAME).read_text())
            self.assertEqual(metadata, {"format": 1, "job_uuid": JOB_UUID, "retain": False,
                                        "owner_pid": os.getpid(), "process_group": os.getpgrp(),
                                        "pid_namespace": process_namespace()})
        self.assertFalse(self.scratch.exists())
        self.assertEqual(output.read_bytes(), b"retained output")

    def test_exception_still_removes_scratch_and_releases_lease(self):
        with self.assertRaisesRegex(RuntimeError, "job failed"):
            with JobdirManager(self.job_dir, scratch_dir=self.scratch, job_uuid=JOB_UUID):
                raise RuntimeError("job failed")
        self.assertFalse(self.scratch.exists())

    def test_debug_retention_is_marked_for_cleanup_refusal(self):
        with JobdirManager(self.job_dir, True, scratch_dir=self.scratch, job_uuid=JOB_UUID) as manager:
            (manager.tmp_dir / "retained.tmp").write_bytes(b"debug")
        self.assertEqual((self.scratch / "tmp.d/retained.tmp").read_bytes(), b"debug")
        self.assertTrue(json.loads((self.scratch / META_FILENAME).read_text())["retain"])

    def test_live_job_lease_blocks_an_independent_process(self):
        with ScratchLease(self.scratch, JOB_UUID):
            probe = subprocess.run([sys.executable, "-c",
                "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDWR); "
                "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)",
                str(self.scratch / LEASE_FILENAME)], capture_output=True, timeout=10)
            self.assertNotEqual(probe.returncode, 0)
        probe = subprocess.run([sys.executable, "-c",
            "import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDWR); "
            "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)",
            str(self.scratch / LEASE_FILENAME)], capture_output=True, timeout=10)
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_existing_or_unknown_scratch_is_never_adopted_or_overwritten(self):
        self.scratch.mkdir()
        original = self.scratch / "unknown.bin"
        original.write_bytes(b"must remain")
        with self.assertRaises(FileExistsError):
            with ScratchLease(self.scratch, JOB_UUID):
                pass
        self.assertEqual(original.read_bytes(), b"must remain")

    def test_legacy_manager_keeps_its_existing_tmp_contract(self):
        with JobdirManager(self.job_dir) as manager:
            self.assertEqual(manager.tmp_dir, self.job_dir / "tmp.d")
        self.assertFalse((self.job_dir / "tmp.d").exists())
        self.assertTrue((self.job_dir / "output.d").is_dir())
