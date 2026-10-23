"""Maintenance readiness must require drained requests and positive worker proof."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.common import JOB_ERROR, JOB_OK, JOB_RUNNING, JOB_WAITING
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.control import _worker_state
from qc_tool.frontend.dashboard.services.maintenance.state import register_worker
from qc_tool.frontend.dashboard.views.jobs.status import refresh_job_statuses_once
from qc_tool.frontend.dashboard.services.jobs.serializers import serialize_job_report


class MaintenanceControlTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_root = Path(self.directory.name) / "maintenance"
        self.settings_override = override_settings(QC_TOOL_MAINTENANCE_DIR=self.state_root, MAINTENANCE_MODE=False)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        user = get_user_model().objects.create_user(username="maintenance-owner")
        self.delivery = Delivery.objects.create(user=user, filename="input.zip", size_bytes=1)

    def job(self, status=JOB_WAITING, worker_url=None):
        return Job.objects.create(delivery=self.delivery, job_status=status, worker_url=worker_url, product_ident="test", product_description="Test")

    def test_ready_preserves_terminal_jobs_and_cancels_queue_and_running(self):
        finished = self.job(JOB_OK)
        waiting = self.job()
        running = self.job(JOB_RUNNING, "http://127.0.0.1:8000/")
        state = maintenance.enable("root", 0)
        with patch("qc_tool.frontend.dashboard.services.maintenance.control._worker_state", return_value=True):
            ready = maintenance.advance(state["generation"])
        self.assertEqual(ready["phase"], "ready")
        self.assertEqual(Job.objects.get(pk=finished.pk).job_status, JOB_OK)
        for job in (waiting, running):
            job.refresh_from_db()
            self.assertEqual(job.job_status, JOB_ERROR)
            self.assertIsNotNone(job.date_finished)
        maintenance.disable("root", ready["generation"])
        self.assertEqual(Job.objects.filter(job_status=JOB_WAITING).count(), 0)

    def test_unreachable_worker_and_pending_processes_block_readiness(self):
        job = self.job(JOB_RUNNING, "http://127.0.0.1:8000/")
        state = maintenance.enable("root", 0)
        for outcome in (OSError("offline"), False):
            with self.subTest(outcome=outcome), patch(
                "qc_tool.frontend.dashboard.services.maintenance.control._worker_state",
                **({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}),
            ):
                pending = maintenance.advance(state["generation"])
                self.assertEqual(pending["phase"], "stopping")
                self.assertTrue(pending["blockers"])
                job.refresh_from_db()
                self.assertEqual(job.job_status, JOB_RUNNING)
                with self.assertRaises(maintenance.MaintenanceError):
                    maintenance.disable("root", state["generation"])

    def test_registered_idle_worker_also_requires_acknowledgment(self):
        register_worker("http://127.0.0.1:8000/")
        state = maintenance.enable("root", 0)
        with patch("qc_tool.frontend.dashboard.services.maintenance.control._worker_state", side_effect=TimeoutError):
            self.assertEqual(maintenance.advance(state["generation"])["phase"], "stopping")

    def test_running_job_without_origin_never_becomes_ready(self):
        self.job(JOB_RUNNING)
        state = maintenance.enable("root", 0)
        self.assertEqual(maintenance.advance(state["generation"])["phase"], "stopping")

    def test_existing_request_must_release_barrier(self):
        waiting = self.job()
        with maintenance.application_activity() as admitted:
            self.assertTrue(admitted)
            state = maintenance.enable("root", 0)
            pending = maintenance.advance(state["generation"])
            self.assertEqual(pending["phase"], "stopping")
            waiting.refresh_from_db()
            self.assertEqual(waiting.job_status, JOB_WAITING)
        self.assertEqual(maintenance.advance(state["generation"])["phase"], "ready")

    def test_stale_enable_and_disable_cannot_reopen_new_state(self):
        state = maintenance.enable("root", 0)
        ready = maintenance.advance(state["generation"])
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.disable("stale", 0)
        maintenance.disable("root", ready["generation"])
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.enable("stale", 0)

    def test_forced_environment_uses_new_durable_worker_generation(self):
        with override_settings(MAINTENANCE_MODE=True):
            forced = maintenance.read_status()
            self.assertEqual(forced["generation"], 1)
            register_worker("http://127.0.0.1:8000/")
            self.assertEqual(maintenance.read_status()["generation"], 1)
            state = maintenance.advance(1)
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.disable("root", 1)
        self.assertTrue(maintenance.read_status()["enabled"])
        self.assertEqual(maintenance.disable("root", state["generation"])["generation"], 2)

    def test_background_refresh_does_not_query_database_while_paused(self):
        maintenance.enable("root", 0)
        with self.assertNumQueries(0):
            refresh_job_statuses_once()

    def test_interrupted_partial_result_cannot_override_terminal_error(self):
        job = self.job(JOB_ERROR)
        report = serialize_job_report({"status": JOB_OK, "steps": []}, job)
        self.assertEqual(report["status"], JOB_ERROR)
        self.assertTrue(report["error_message"])

    def test_browser_api_upload_worker_and_other_admin_routes_are_fenced(self):
        maintenance.enable("root", 0)
        for path in ("/resumable_upload/", "/api/register-delivery", "/pull_job", "/admin/auth/user/"):
            with self.subTest(path=path), self.assertNumQueries(0):
                response = self.client.post(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response["Retry-After"], "60")
        self.assertEqual(self.client.get("/health").status_code, 200)

    @patch("qc_tool.frontend.dashboard.authentication.decorators.auth_worker", return_value=True)
    def test_worker_state_remains_authenticated_and_readonly_during_pause(self, _auth):
        maintenance.enable("root", 0)
        response = self.client.post(reverse("worker_maintenance"))
        self.assertEqual(response.status_code, 401)
        with self.assertNumQueries(0):
            response = self.client.post(reverse("worker_maintenance"), HTTP_AUTHORIZATION="WorkerToken test-secret")
        self.assertEqual(response.json(), {"enabled": True, "generation": 1})
        self.assertIn("no-store", response["Cache-Control"])

    def test_corrupt_state_fails_closed_for_normal_routes_and_worker(self):
        maintenance.read_status()
        (self.state_root / "state.json").write_text("broken")
        self.assertEqual(self.client.get("/deliveries/").status_code, 503)
        with patch("qc_tool.frontend.dashboard.authentication.decorators.auth_worker", return_value=True):
            self.assertEqual(self.client.post(reverse("worker_maintenance"), HTTP_AUTHORIZATION="WorkerToken test").status_code, 503)

    def test_operator_retirement_requires_explicit_verified_stop(self):
        url = "http://127.0.0.1:8000/"
        register_worker(url)
        job = self.job(JOB_RUNNING, url)
        maintenance.enable("root", 0)
        with self.assertRaises(CommandError):
            call_command("maintenance", "retire-worker", worker_url=url, generation=1)
        call_command("maintenance", "retire-worker", worker_url=url, generation=1, verified_stopped=True, stdout=MagicMock())
        job.refresh_from_db()
        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertEqual(maintenance.read_status()["workers"], [])
        self.assertEqual(maintenance.read_status()["phase"], "stopping")
        self.assertEqual(maintenance.advance(2)["phase"], "ready")

    @patch("qc_tool.frontend.dashboard.services.maintenance.workers.get_worker_token", return_value="private")
    @patch("qc_tool.frontend.dashboard.services.maintenance.workers.HTTPConnection")
    def test_worker_ack_requires_exact_generation_and_positive_quiescence(self, connection_class, _token):
        connection = connection_class.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"enabled":true,"generation":1,"quiescent":true}'
        self.assertTrue(_worker_state("http://127.0.0.1:8000/", {"enabled": True, "generation": 1}))
        self.assertEqual(connection.request.call_args.args[:2], ("PUT", "/maintenance"))
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Authorization"], "WorkerToken private")
        connection_class.assert_called_with("127.0.0.1", 8000, timeout=5)
        response.read.return_value = b'{"enabled":true,"generation":0,"quiescent":true}'
        with self.assertRaises(ValueError):
            _worker_state("http://127.0.0.1:8000/", {"enabled": True, "generation": 1})
        with self.assertRaises(ValueError):
            _worker_state("http://untrusted.example:8000/", {"enabled": True, "generation": 1})

    def test_database_failure_keeps_stopping_and_safe_blocker(self):
        from django.db import OperationalError
        state = maintenance.enable("root", 0)
        with patch.object(Job.objects, "filter", side_effect=OperationalError("private connection detail")):
            result = maintenance.advance(state["generation"])
        self.assertEqual(result["phase"], "stopping")
        self.assertNotIn("private connection detail", str(result["blockers"]))
        self.assertIn("database is unavailable", result["blockers"][0])

    def test_retirement_invalidates_ready_before_database_mutation(self):
        from django.db import OperationalError
        register_worker("http://127.0.0.1:8000/")
        state = maintenance.enable("root", 0)
        with patch("qc_tool.frontend.dashboard.services.maintenance.control._worker_state", return_value=True):
            maintenance.advance(state["generation"])
        with patch.object(Job.objects, "filter", side_effect=OperationalError), self.assertRaises(maintenance.MaintenanceError):
            maintenance.retire_worker("http://127.0.0.1:8000/", "operator", state["generation"], verified_stopped=True)
        self.assertEqual(maintenance.read_status()["phase"], "stopping")
        self.assertEqual(maintenance.read_status()["readiness_checked_at"], "")
