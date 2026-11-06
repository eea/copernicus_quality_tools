"""Operator scratch cleanup obeys SQL identity and the shared maintenance barrier."""

from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from qc_tool.common import CONFIG, JOB_OK, JOB_RUNNING
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.storage.scratch_retention import LEASE_FILENAME, META_FILENAME
from qc_tool.worker.scratch import process_namespace


class ScratchStorageCommandTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.enterContext(patch.dict(CONFIG, data_root=self.root / "data", work_dir=self.root / "data/jobs",
            incoming_dir=self.root / "data/incoming", boundary_dir=self.root / "data/boundaries",
            submission_dir=self.root / "data/submissions", specifications_dir=self.root / "data/specifications",
            shared_state_dir=self.root / "shared", frontend_state_dir=self.root / "frontend",
            scratch_dir=self.scratch, log_dir=self.root / "logs"))
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers", MAINTENANCE_MODE=False))
        owner = get_user_model().objects.create_user("scratch-owner")
        delivery = Delivery.objects.create(user=owner, filename="input.zip", size_bytes=1)
        self.job = Job.objects.create(delivery=delivery, job_status=JOB_OK,
            product_ident="test", product_description="Test")
        self.child = self.make_scratch(self.job.pk)

    def make_scratch(self, identifier):
        child = self.scratch / identifier.hex
        child.mkdir(mode=0o700)
        marker = child / META_FILENAME
        marker.write_text(json.dumps({"format": 1, "job_uuid": str(identifier), "retain": False,
            "owner_pid": 1_000_000_000, "process_group": 1_000_000_000,
            "pid_namespace": process_namespace()}))
        marker.chmod(0o600)
        (child / LEASE_FILENAME).touch(mode=0o600)
        (child / "tmp.d").mkdir()
        (child / "tmp.d/payload.bin").write_bytes(b"scratch")
        old = time.time() - 2 * 86400
        for path in sorted(child.rglob("*"), reverse=True):
            os.utime(path, (old, old))
        os.utime(child, (old, old))
        return child

    def run_command(self, **options):
        output = StringIO()
        call_command("scratch_storage", stdout=output, **options)
        return json.loads(output.getvalue())

    def test_plan_is_read_only_apply_requires_ready_generation_and_exact_review(self):
        plan = self.run_command()["scratch"][0]
        self.assertTrue(plan["eligible"])
        self.assertFalse((self.root / "maintenance").exists())
        apply = {"apply": True, "job": str(self.job.pk), "review_token": plan["review_token"], "generation": 0}
        with self.assertRaisesMessage(CommandError, "Enable maintenance"):
            self.run_command(**apply)
        enabled = maintenance.enable("operator", 0)
        ready = maintenance.advance(enabled["generation"])
        self.assertEqual(ready["phase"], "ready")
        with self.assertRaisesMessage(CommandError, "Maintenance changed"):
            self.run_command(**apply)
        apply["generation"] = ready["generation"]
        apply["review_token"] = "wrong"
        with self.assertRaisesMessage(CommandError, "Plan cleanup again"):
            self.run_command(**apply)
        self.assertTrue(self.child.exists())
        apply["review_token"] = plan["review_token"]
        self.assertTrue(self.run_command(**apply)["removed"])
        self.assertFalse(self.child.exists())
        self.assertEqual(Job.objects.get(pk=self.job.pk).job_status, JOB_OK)

    def test_unknown_or_running_job_never_receives_cleanup_authority(self):
        unknown = uuid4()
        unknown_child = self.make_scratch(unknown)
        plans = self.run_command()["scratch"]
        unknown_plan = next(item for item in plans if item.get("job_uuid") == str(unknown))
        self.assertFalse(unknown_plan["eligible"])
        self.assertNotIn("review_token", unknown_plan)
        ready = maintenance.advance(maintenance.enable("operator", 0)["generation"])
        Job.objects.filter(pk=self.job.pk).update(job_status=JOB_RUNNING)
        with self.assertRaisesMessage(CommandError, "recorded terminal"):
            self.run_command(apply=True, job=str(self.job.pk), review_token="any", generation=ready["generation"])
        with self.assertRaisesMessage(CommandError, "recorded terminal"):
            self.run_command(apply=True, job=str(unknown), review_token="any", generation=ready["generation"])
        self.assertTrue(self.child.exists())
        self.assertTrue(unknown_child.exists())
