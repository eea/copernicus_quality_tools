"""Scratch cleanup must prove ownership and inactivity without erasing evidence."""

import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from qc_tool.storage.layout import runtime_paths
from qc_tool.storage.scratch_retention import (
    LEASE_FILENAME, META_FILENAME, ScratchRetentionError,
    inspect_scratch, remove_scratch, validate_scratch_layout,
)
from qc_tool.worker.scratch import process_namespace


class ScratchRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "scratch"
        self.root.mkdir()
        self.identifier = uuid4()
        self.child = self.root / self.identifier.hex
        self.child.mkdir(mode=0o700)
        self.metadata = {"format": 1, "job_uuid": str(self.identifier), "retain": False,
                         "owner_pid": 1_000_000_000, "process_group": 1_000_000_000,
                         "pid_namespace": process_namespace()}
        self.write_metadata()
        (self.child / LEASE_FILENAME).touch(mode=0o600)
        (self.child / "unpacked").mkdir()
        (self.child / "unpacked" / "payload.bin").write_bytes(b"temporary data")
        self.now = time.time() + 2 * 86400

    def write_metadata(self):
        path = self.child / META_FILENAME
        path.write_text(json.dumps(self.metadata))
        path.chmod(0o600)

    def plan(self):
        return inspect_scratch(self.root, now=self.now)[0]

    def test_plan_preserves_bytes_and_exact_apply_removes_only_owned_scratch(self):
        evidence = self.root.parent / "evidence"
        evidence.mkdir()
        (evidence / "report.pdf").write_bytes(b"retained evidence")
        (evidence / "operation.json").write_bytes(b"recovery authority")
        plan = self.plan()
        self.assertTrue(plan["eligible"])
        self.assertTrue((self.child / "unpacked" / "payload.bin").exists())
        result = remove_scratch(self.root, str(self.identifier), plan["review_token"], now=self.now)
        self.assertTrue(result["removed"])
        self.assertFalse(self.child.exists())
        self.assertEqual((evidence / "report.pdf").read_bytes(), b"retained evidence")
        self.assertEqual((evidence / "operation.json").read_bytes(), b"recovery authority")

    def test_changed_review_is_refused(self):
        plan = self.plan()
        (self.child / "unpacked" / "payload.bin").write_bytes(b"changed temporary bytes")
        with self.assertRaisesRegex(ScratchRetentionError, "Plan cleanup again"):
            remove_scratch(self.root, self.identifier, plan["review_token"], now=self.now)
        self.assertTrue(self.child.exists())

    def test_recent_activity_and_debug_retention_are_refused(self):
        self.assertFalse(inspect_scratch(self.root)[0]["eligible"])
        self.metadata["retain"] = True
        self.write_metadata()
        self.assertIn("debugging", self.plan()["reason"])

    def test_live_lease_owner_and_process_group_are_refused(self):
        with open(self.child / LEASE_FILENAME) as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn("active", self.plan()["reason"])
        self.metadata["owner_pid"] = os.getpid()
        self.write_metadata()
        self.assertIn("still exists", self.plan()["reason"])
        self.metadata["owner_pid"] = 1_000_000_000
        self.metadata["process_group"] = os.getpgrp()
        self.write_metadata()
        self.assertIn("still exists", self.plan()["reason"])

    def test_other_process_namespace_is_never_assumed_dead(self):
        self.metadata["pid_namespace"] = "different-worker-namespace"
        self.write_metadata()
        self.assertIn("different worker PID namespace", self.plan()["reason"])

    def test_links_unknown_directories_and_missing_ownership_are_refused(self):
        target = self.root.parent / "secret"
        target.write_bytes(b"never remove")
        (self.child / "link").symlink_to(target)
        self.assertIn("link or special", self.plan()["reason"])
        (self.child / "link").unlink()
        os.link(target, self.child / "linked")
        self.assertIn("hard-linked", self.plan()["reason"])
        (self.child / "linked").unlink()
        (self.child / META_FILENAME).unlink()
        self.assertFalse(self.plan()["eligible"])
        (self.root / "job_unknown").mkdir()
        results = inspect_scratch(self.root, now=self.now)
        self.assertTrue(all(not item["eligible"] for item in results))
        self.assertEqual(target.read_bytes(), b"never remove")

    def test_symlink_root_is_refused_and_missing_root_is_not_created(self):
        linked = self.root.parent / "alias"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            inspect_scratch(linked, now=self.now)
        missing = self.root.parent / "missing"
        self.assertEqual(inspect_scratch(missing), [])
        self.assertFalse(missing.exists())

    def test_nonprivate_child_and_publicly_writable_root_are_refused(self):
        self.child.chmod(0o755)
        self.assertIn("remain private", self.plan()["reason"])
        self.child.chmod(0o700)
        self.root.chmod(0o777)
        with self.assertRaisesRegex(ScratchRetentionError, "group/public writes"):
            inspect_scratch(self.root, now=self.now)
        self.assertTrue((self.child / "unpacked/payload.bin").exists())

    def test_durable_storage_overlap_and_legacy_layout_are_refused(self):
        base = self.root.parent
        config = {"data_root": base / "data", "work_dir": base / "data" / "jobs",
                  "incoming_dir": base / "data" / "incoming", "frontend_state_dir": base / "private",
                  "scratch_dir": self.root}
        self.assertEqual(validate_scratch_layout(runtime_paths(config)), self.root)
        config["scratch_dir"] = config["work_dir"] / "tmp"
        with self.assertRaisesRegex(ScratchRetentionError, "overlaps"):
            validate_scratch_layout(runtime_paths(config))
        with self.assertRaisesRegex(ScratchRetentionError, "legacy"):
            validate_scratch_layout(runtime_paths({"work_dir": base / "work"}))


if __name__ == "__main__":
    unittest.main()
