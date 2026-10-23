"""Maintenance admission races and complete validator-group interruption."""

import json
import os
import signal
import subprocess
import sys
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, mock_open, patch

from qc_tool.test.test_worker_service_auth import request_worker
from qc_tool.worker import scheduler


class WorkerMaintenanceTests(TestCase):
    def setUp(self):
        self.state = scheduler.WorkerMaintenance()

    def test_starts_closed_and_rejects_stale_or_conflicting_unpause(self):
        self.assertFalse(self.state.begin_pull())
        self.state.update(False, 2)
        self.assertTrue(self.state.begin_pull())
        self.state.finish_pull()
        self.state.update(True, 3)
        self.state.update(False, 2)
        self.state.update(False, 3)
        self.assertTrue(self.state.paused)
        self.assertTrue(self.state.snapshot()["quiescent"])

    def test_inflight_pull_blocks_readiness_and_cannot_launch_after_pause(self):
        self.state.update(False, 1)
        self.assertTrue(self.state.begin_pull())
        self.state.update(True, 2)
        self.assertFalse(self.state.snapshot()["quiescent"])
        self.assertFalse(self.state.register(MagicMock()))
        self.state.finish_pull()
        self.assertTrue(self.state.snapshot()["quiescent"])

    def test_failed_poll_interrupts_and_valid_same_generation_recovers(self):
        self.state.update(False, 1)
        controller = MagicMock()
        self.assertTrue(self.state.register(controller))
        self.state.unavailable()
        controller.request_stop.assert_called_once_with()
        self.assertTrue(self.state.paused)
        self.assertFalse(self.state.snapshot()["quiescent"])
        self.state.update(False, 1)
        self.assertFalse(self.state.paused)
        self.state.unregister(controller)
        self.assertTrue(self.state.snapshot()["quiescent"])

    def test_invalid_generation_never_changes_admission(self):
        for generation in (-1, True, "1", None):
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                self.state.update(False, generation)
        self.assertTrue(self.state.paused)

    def test_pause_between_controller_registration_and_launch_is_fenced(self):
        self.state.update(False, 1)
        controller = scheduler.JobController({
            "job_uuid": "00000000-0000-0000-0000-000000000001",
            "product_ident": "product", "skip_steps": None,
            "username": "alice", "filename": "delivery.zip",
        })
        self.assertTrue(self.state.register(controller))
        controller._registered = True
        self.state.update(True, 2)
        with (
            patch.object(scheduler, "maintenance", self.state),
            patch.object(scheduler, "Popen") as popen,
            patch.object(scheduler, "open", mock_open()),
            patch.object(scheduler, "job_table", scheduler.JobTable()),
        ):
            controller.run(Event())
        popen.assert_not_called()
        self.assertTrue(self.state.snapshot()["quiescent"])


class WorkerMaintenanceProtocolTests(TestCase):
    def test_continuous_short_jobs_cannot_starve_maintenance_polls(self):
        worker = scheduler.Scheduler("http://frontend:8000/pull_job")
        state = scheduler.WorkerMaintenance()
        state.update(False, 1)
        with (
            patch.object(scheduler, "maintenance", state),
            patch.object(scheduler, "job_table", scheduler.JobTable(max_slots=1)),
            patch.object(scheduler, "monotonic", return_value=0),
            patch.object(scheduler, "sleep") as sleep,
            patch.object(scheduler, "JobController") as controller,
            patch.object(worker, "pull_job", return_value={"job_uuid": "short-job"}) as pull,
            patch.object(worker, "refresh_maintenance", side_effect=(None, None, RuntimeError("end-loop"))) as refresh,
            self.assertRaisesRegex(RuntimeError, "end-loop"),
        ):
            controller.return_value.start.return_value = True
            worker.run()
        self.assertEqual(refresh.call_count, 3)
        self.assertEqual(pull.call_count, 2)
        sleep.assert_not_called()  # No extra delay when completed jobs free capacity.
        self.assertTrue(state.snapshot()["quiescent"])

    def test_claim_batch_fills_all_available_slots(self):
        worker = scheduler.Scheduler("http://frontend:8000/pull_job")
        state = scheduler.WorkerMaintenance()
        state.update(False, 1)
        table = scheduler.JobTable(max_slots=3)

        def controller(args):
            def start():
                table.put(args["job_uuid"])
                return True
            return SimpleNamespace(start=start)

        with (
            patch.object(scheduler, "maintenance", state),
            patch.object(scheduler, "job_table", table),
            patch.object(scheduler, "monotonic", return_value=0),
            patch.object(scheduler, "JobController", side_effect=controller),
            patch.object(worker, "pull_job", side_effect=[{"job_uuid": str(i)} for i in range(3)]) as pull,
        ):
            self.assertFalse(worker._claim_batch(10))
        self.assertEqual(pull.call_count, 3)
        self.assertEqual(table.free_slots, 0)

    def test_claim_batch_yields_when_poll_deadline_passes(self):
        worker = scheduler.Scheduler("http://frontend:8000/pull_job")
        state = scheduler.WorkerMaintenance()
        state.update(False, 1)
        with (
            patch.object(scheduler, "maintenance", state),
            patch.object(scheduler, "job_table", scheduler.JobTable(max_slots=3)),
            patch.object(scheduler, "monotonic", side_effect=(0, 11)),
            patch.object(scheduler, "JobController") as controller,
            patch.object(worker, "pull_job", return_value={"job_uuid": "short-job"}) as pull,
        ):
            controller.return_value.start.return_value = True
            self.assertFalse(worker._claim_batch(10))
        pull.assert_called_once_with()
        self.assertTrue(state.snapshot()["quiescent"])

    def test_fatal_scheduler_loop_closes_admission_and_reports_unhealthy(self):
        worker = scheduler.Scheduler("http://frontend:8000/pull_job")
        state = scheduler.WorkerMaintenance()
        state.update(False, 1)
        controller = MagicMock()
        state.register(controller)
        with (
            patch.object(scheduler, "maintenance", state),
            patch.object(worker, "run", side_effect=RuntimeError("unexpected failure")),
            patch.object(scheduler, "log"),
        ):
            worker._run_guarded()
        self.assertFalse(worker.healthy)
        self.assertTrue(state.paused)
        controller.request_stop.assert_called_once_with()
        with patch.object(scheduler.bottle.default_app(), "scheduler", worker, create=True):
            response = request_worker("/health")
        self.assertTrue(response["status"].startswith("503 "))
        self.assertEqual(json.loads(response["body"]), {"status": "unavailable"})

    def test_scheduler_polls_maintenance_even_when_all_slots_are_occupied(self):
        worker = scheduler.Scheduler("http://frontend:8000/pull_job")
        full_table = scheduler.JobTable(max_slots=1)
        full_table.put("already-running")
        with (
            patch.object(scheduler, "job_table", full_table),
            patch.object(worker, "refresh_maintenance") as refresh,
            patch.object(worker, "pull_job") as pull,
            patch.object(scheduler, "sleep", side_effect=RuntimeError("end-loop")),
            self.assertRaisesRegex(RuntimeError, "end-loop"),
        ):
            worker.run()
        refresh.assert_called_once_with()
        pull.assert_not_called()

    @patch.object(scheduler, "auth_worker", return_value=True)
    def test_authenticated_put_is_bounded_and_generation_guarded(self, _auth):
        state = scheduler.WorkerMaintenance()
        with patch.object(scheduler, "maintenance", state):
            response = request_worker(
                "/maintenance", method="PUT",
                authorization="WorkerToken valid-token",
                body=b'{"enabled":true,"generation":2}',
            )
            self.assertTrue(response["status"].startswith("200 "))
            self.assertEqual(json.loads(response["body"]), {
                "enabled": True, "generation": 2, "quiescent": True,
            })
            for payload in (
                b'{"enabled":false,"generation":true}',
                b'{"enabled":false,"generation":-1}',
                b'{"enabled":false,"generation":3,"unexpected":1}',
                b'{"enabled":true,"enabled":false,"generation":3}',
                b"x" * (scheduler.MAX_MAINTENANCE_BYTES + 1),
            ):
                response = request_worker(
                    "/maintenance", method="PUT",
                    authorization="WorkerToken valid-token", body=payload,
                )
                self.assertTrue(response["status"].startswith("400 "))

    def test_put_requires_worker_authentication(self):
        response = request_worker(
            "/maintenance", method="PUT",
            body=b'{"enabled":true,"generation":1}',
        )
        self.assertTrue(response["status"].startswith("401 "))

    @patch.object(scheduler, "get_worker_token", return_value="private-secret")
    @patch.object(scheduler, "_worker_url_opener")
    def test_poll_uses_sibling_post_and_fails_closed(self, opener, _token):
        state = scheduler.WorkerMaintenance()
        response = opener.open.return_value.__enter__.return_value
        response.read.return_value = b'{"enabled":false,"generation":3}'
        worker = scheduler.Scheduler("http://frontend:8000/pull_job")
        with patch.object(scheduler, "maintenance", state):
            self.assertFalse(worker.refresh_maintenance()["enabled"])
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://frontend:8000/worker_maintenance")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"), "WorkerToken private-secret")
            self.assertNotIn("private-secret", request.full_url)
            opener.open.side_effect = OSError("offline")
            self.assertTrue(worker.refresh_maintenance()["enabled"])
            opener.open.side_effect = None
            response.read.return_value = b'{"enabled":true,"enabled":false,"generation":3}'
            self.assertTrue(worker.refresh_maintenance()["enabled"])


class ValidatorProcessGroupTests(TestCase):
    @patch.object(scheduler, "TERMINATION_GRACE_SECONDS", 2)
    def test_termination_stops_and_reaps_descendant_process_group(self):
        # The validator parent handles TERM by reaping its child. This lets
        # the test assert actual group disappearance, including descendants.
        script = """
import signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def stop(signum, frame):
    child.wait(timeout=5)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
print(child.pid, flush=True)
while True:
    time.sleep(1)
"""
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", script],
            start_new_session=True, stdout=subprocess.PIPE, text=True,
        )
        try:
            descendant_pid = int(process.stdout.readline())
            self.assertEqual(os.getpgid(descendant_pid), process.pid)
            controller = scheduler.JobController({})
            controller.process = process
            controller._terminate_group()
            process.wait(timeout=5)
            self.assertFalse(scheduler._process_group_exists(process.pid))
            with self.assertRaises(ProcessLookupError):
                os.kill(descendant_pid, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            process.stdout.close()

    def test_escalates_to_kill_when_group_ignores_term(self):
        controller = scheduler.JobController({})
        controller.process = MagicMock(pid=123)
        with (
            patch.object(scheduler, "_process_group_exists", return_value=True),
            patch.object(scheduler, "monotonic", side_effect=(0, 10)),
            patch.object(scheduler.os, "killpg") as killpg,
        ):
            controller._terminate_group()
        self.assertEqual(killpg.call_args_list[0].args, (123, signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[1].args, (123, signal.SIGKILL))
