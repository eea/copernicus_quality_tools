"""Filesystem admission and middleware keep readiness meaningful."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.sessions.models import Session
from django.db import connection
from django.http import HttpResponse, StreamingHttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.frontend.dashboard.middleware import (
    MaintenanceModeMiddleware, MaintenanceSessionMiddleware,
)
from qc_tool.frontend.dashboard.services.maintenance import state
from qc_tool.frontend.dashboard.services.maintenance import control
from qc_tool.frontend.dashboard.services.maintenance.operations import pin_operation


class MaintenanceProgressTests(TestCase):
    """Automatic progress cannot invalidate a concurrent readiness decision."""

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.root = Path(directory) / "maintenance"
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=self.root, MAINTENANCE_MODE=False,
        ))

    def ready(self):
        status = control.enable("progress-administrator", expected_generation=0)
        status.update(
            phase="ready", blockers=[], workers=["http://127.0.0.8:8000/"],
            readiness_checked_at="2026-10-20T10:05:00+00:00",
        )
        with state.file_lock("control"):
            state.write_status(status)
        return state.read_status()

    def test_automatic_progress_preserves_ready_without_probes_or_writes(self):
        from qc_tool.frontend.dashboard.models import Job

        ready = self.ready()
        before = (self.root / "state.json").read_bytes()
        with (
            patch.object(control, "_mark_stopping") as mark_stopping,
            patch.object(control, "_worker_blockers") as workers,
            patch.object(control, "_stop_jobs") as stop_jobs,
            patch.object(control, "write_status") as write_status,
            patch.object(Job.objects, "filter") as jobs,
            self.assertNumQueries(0),
        ):
            result = control.advance(ready["generation"], stopping_only=True)

        self.assertEqual(result, ready)
        self.assertEqual((self.root / "state.json").read_bytes(), before)
        for operation in (mark_stopping, workers, stop_jobs, write_status, jobs):
            operation.assert_not_called()

    def test_automatic_progress_still_completes_stopping_and_job_history(self):
        from qc_tool.common import JOB_ERROR, JOB_WAITING
        from qc_tool.frontend.dashboard.models import Delivery, Job

        owner = get_user_model().objects.create_user(username="progress-job-owner")
        delivery = Delivery.objects.create(user=owner, filename="input.zip", size_bytes=1)
        job = Job.objects.create(
            delivery=delivery, job_status=JOB_WAITING,
            product_ident="test", product_description="Test",
        )
        stopping = control.enable("progress-administrator", expected_generation=0)

        result = control.advance(stopping["generation"], stopping_only=True)

        self.assertEqual(result["phase"], "ready")
        self.assertTrue(result["readiness_checked_at"])
        job.refresh_from_db()
        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertIsNotNone(job.date_finished)

    def test_explicit_recheck_still_probes_and_invalidates_old_readiness(self):
        ready = self.ready()
        with patch.object(control, "_worker_state", return_value=False) as probe:
            result = control.advance(ready["generation"])

        probe.assert_called_once()
        self.assertEqual(result["phase"], "stopping")
        self.assertEqual(result["readiness_checked_at"], "")
        self.assertTrue(result["blockers"])

    def test_ready_noop_still_requires_current_generation(self):
        ready = self.ready()
        before = (self.root / "state.json").read_bytes()

        with self.assertRaisesMessage(state.MaintenanceError, "Maintenance state changed"):
            control.advance(ready["generation"] - 1, stopping_only=True)

        self.assertEqual((self.root / "state.json").read_bytes(), before)

    def test_ready_noop_still_rejects_active_transfer(self):
        ready = self.ready()
        before = (self.root / "state.json").read_bytes()
        with state.file_lock("control"):
            pin_operation("a59ce9c5-696e-470c-9ff5-c02b42d59d52", "export", ready["generation"])

        with self.assertRaisesMessage(state.MaintenanceError, "owns maintenance"):
            control.advance(ready["generation"], stopping_only=True)

        self.assertEqual((self.root / "state.json").read_bytes(), before)

    def test_ready_noop_still_serializes_with_other_control_actions(self):
        ready = self.ready()
        with state.file_lock("control"), self.assertRaisesMessage(
            state.MaintenanceBusy, "Another maintenance action is in progress",
        ):
            control.advance(ready["generation"], stopping_only=True)

    def test_automatic_progress_cannot_enable_maintenance(self):
        off = state.read_status()
        with self.assertRaisesMessage(state.MaintenanceError, "Enable maintenance"):
            control.advance(off["generation"], stopping_only=True)

        self.assertFalse(state.read_status()["enabled"])


class MaintenanceAdmissionTests(SimpleTestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.root = Path(directory) / "maintenance"
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=self.root, MAINTENANCE_MODE=False,
        ))
        state.read_status()
        self.factory = RequestFactory()

    def persist(self, **updates):
        status = state.read_status()
        status.update(updates)
        with state.file_lock("control"):
            state.write_status(status)
        return status

    def test_control_status_probe_does_not_create_a_missing_lock(self):
        lock = self.root / "control.lock"
        self.assertFalse(lock.exists())
        self.assertFalse(state.control_active())
        self.assertFalse(lock.exists())

    def test_control_status_probe_does_not_create_missing_storage(self):
        missing = self.root / "not-created"
        with override_settings(QC_TOOL_MAINTENANCE_DIR=missing):
            self.assertFalse(state.control_active())
        self.assertFalse(missing.exists())

    def test_control_status_probe_observes_admission_without_changing_state(self):
        before = (self.root / "state.json").read_bytes()
        with state.file_lock("control"):
            self.assertTrue(state.control_active())
        self.assertFalse(state.control_active())
        self.assertEqual((self.root / "state.json").read_bytes(), before)

    def test_control_status_probe_refuses_an_unsafe_lock(self):
        target = self.root / "not-a-lock"
        target.write_text("preserve this")
        (self.root / "control.lock").symlink_to(target)
        with self.assertRaises(state.MaintenanceError):
            state.control_active()
        self.assertEqual(target.read_text(), "preserve this")

    def test_transition_survives_fresh_reads_and_refuses_new_work(self):
        self.persist(enabled=True, phase="stopping", generation=7)
        self.assertEqual(state.read_status()["generation"], 7)
        with state.application_activity() as admitted:
            self.assertFalse(admitted)
        self.assertTrue((self.root / "state.json").exists())

    def test_activity_is_visible_to_a_separate_process(self):
        script = """
import fcntl, sys
with open(sys.argv[1], 'a+b') as handle:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(2)
"""
        with state.application_activity() as admitted:
            self.assertTrue(admitted)
            blocked = subprocess.run(
                [sys.executable, "-c", script, str(self.root / "activity.lock")],
                check=False, capture_output=True, timeout=5,
            )
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            # A persisted pause cannot certify an older admitted request done.
            self.persist(enabled=True, phase="stopping", generation=1)
            with state.file_lock("activity", blocking=False) as drained:
                self.assertFalse(drained)
        with state.file_lock("activity", blocking=False) as drained:
            self.assertTrue(drained)

    def test_corrupt_state_blocks_requests_without_invoking_the_view(self):
        handler = Mock(return_value=HttpResponse("should not run"))
        middleware = MaintenanceModeMiddleware(handler)
        for raw in (b"{", b"[]", b'{"enabled":false,"phase":"ready","generation":0,"workers":[],"blockers":[]}'):
            with self.subTest(raw=raw):
                (self.root / "state.json").write_bytes(raw)
                response = middleware(self.factory.post("/api/upload"))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(json.loads(response.content)["error"], "maintenance")
        handler.assert_not_called()

    def test_duplicate_authority_fields_are_refused_without_reopening(self):
        payload = json.dumps({
            key: value for key, value in state.read_status().items()
            if key not in {"forced", "environment_only"}
        })
        # Last-field-wins JSON decoding would silently accept this as OFF.
        (self.root / "state.json").write_text('{"enabled": true, ' + payload[1:])
        with self.assertRaises(state.MaintenanceError):
            state.read_status()
        handler = Mock(return_value=HttpResponse("should not run"))
        response = MaintenanceModeMiddleware(handler)(self.factory.post("/api/upload"))
        self.assertEqual(response.status_code, 503)
        handler.assert_not_called()

    def test_enabled_worker_registration_does_not_rewrite_state(self):
        self.persist(enabled=True, phase="ready", generation=3)
        before = (self.root / "state.json").read_bytes()
        registered = state.register_worker("http://127.0.0.8:8000/")
        self.assertTrue(registered["enabled"])
        self.assertEqual((self.root / "state.json").read_bytes(), before)
        self.assertEqual(registered["workers"], [])

    def test_forced_environment_materializes_a_new_stable_generation(self):
        self.persist(generation=4)
        with override_settings(MAINTENANCE_MODE=True):
            forced = state.register_worker("http://127.0.0.8:8000/")
            self.assertTrue(forced["enabled"])
            self.assertEqual(forced["generation"], 5)
            self.assertEqual(state.register_worker("http://127.0.0.8:8000/")["generation"], 5)
        # Removing the emergency environment flag cannot reopen persisted work.
        self.assertTrue(state.read_status()["enabled"])
        self.assertEqual(state.read_status()["generation"], 5)

    def test_streaming_retains_activity_until_response_close(self):
        response = MaintenanceModeMiddleware(
            lambda request: StreamingHttpResponse(iter((b"one", b"two"))),
        )(self.factory.get("/deliveries/export.csv"))
        try:
            self.persist(enabled=True, phase="stopping", generation=1)
            with state.file_lock("activity", blocking=False) as drained:
                self.assertFalse(drained)
            self.assertEqual(b"".join(response.streaming_content), b"onetwo")
            with state.file_lock("activity", blocking=False) as drained:
                self.assertFalse(drained)
        finally:
            response.close()
        with state.file_lock("activity", blocking=False) as drained:
            self.assertTrue(drained)

    def test_unconsumed_stream_releases_activity_when_response_closes(self):
        response = MaintenanceModeMiddleware(
            lambda request: StreamingHttpResponse(iter((b"one", b"two"))),
        )(self.factory.get("/deliveries/export.csv"))
        response.close()
        with state.file_lock("activity", blocking=False) as drained:
            self.assertTrue(drained)

    def test_stream_exception_retains_activity_until_response_close(self):
        def chunks():
            yield b"one"
            raise RuntimeError("stream failed")

        response = MaintenanceModeMiddleware(
            lambda request: StreamingHttpResponse(chunks()),
        )(self.factory.get("/deliveries/export.csv"))
        try:
            with self.assertRaisesRegex(RuntimeError, "stream failed"):
                list(response.streaming_content)
            with state.file_lock("activity", blocking=False) as drained:
                self.assertFalse(drained)
        finally:
            response.close()
        with state.file_lock("activity", blocking=False) as drained:
            self.assertTrue(drained)

    def test_health_never_reads_broken_maintenance_state(self):
        (self.root / "state.json").write_bytes(b"bad state")
        handler = Mock()
        response = MaintenanceModeMiddleware(handler)(self.factory.get("/health"))
        self.assertEqual(response.status_code, 200)
        handler.assert_not_called()

    def test_missing_state_in_existing_directory_is_closed_not_off(self):
        (self.root / "state.json").unlink()
        with self.assertRaises(state.MaintenanceError):
            state.read_status()
        response = MaintenanceModeMiddleware(Mock())(self.factory.get("/api/upload"))
        self.assertEqual(response.status_code, 503)

    def test_existing_empty_directory_is_not_automatically_initialized(self):
        existing = self.root.parent / "preexisting"
        existing.mkdir()
        with override_settings(QC_TOOL_MAINTENANCE_DIR=existing), self.assertRaises(state.MaintenanceError):
            state.read_status()
        self.assertFalse((existing / "state.json").exists())

    def test_symlinked_state_and_lock_do_not_get_followed(self):
        state_file = self.root / "state.json"
        target = self.root.parent / "original.json"
        state_file.rename(target)
        state_file.symlink_to(target)
        with self.assertRaises(state.MaintenanceError):
            state.read_status()
        state_file.unlink()
        target.rename(state_file)
        (self.root / "activity.lock").symlink_to(state_file)
        with self.assertRaises(state.MaintenanceError):
            with state.file_lock("activity"):
                self.fail("Symlinked lock was followed")

    def test_invalid_state_versions_and_fields_are_refused(self):
        initial = state.read_status()
        for update in ({"format_version": 99}, {"actor": []}, {"workers": ["http://evil.example:8000/"]}, {"blockers": [None]}, {"changed_at": "not a date"}):
            with self.subTest(update=update):
                payload = {key: value for key, value in initial.items() if key not in {"forced", "environment_only"}}
                payload.update(update)
                (self.root / "state.json").write_text(json.dumps(payload))
                with self.assertRaises(state.MaintenanceError):
                    state.read_status()

    def test_lock_does_not_relabel_errors_from_protected_code(self):
        with self.assertRaisesRegex(OSError, "application failure"):
            with state.file_lock("activity"):
                raise OSError("application failure")


class MaintenanceReadOnlySessionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="maintenance-session", password="test-password",
        )
        client = Client()
        client.force_login(self.user)
        self.session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
        self.factory = RequestFactory()

    def middleware_response(self, path):
        middleware = MaintenanceSessionMiddleware(AuthenticationMiddleware(
            lambda request: HttpResponse(str(request.user.is_authenticated)),
        ))
        request = self.factory.get(path, HTTP_COOKIE="{}={}".format(
            settings.SESSION_COOKIE_NAME, self.session_key,
        ))
        with CaptureQueriesContext(connection) as queries:
            response = middleware(request)
        mutations = [
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))
        ]
        self.assertEqual(mutations, [])
        return response

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_valid_control_sessions_never_save_on_response(self):
        for path in ("/admin/maintenance/", "/worker_maintenance"):
            with self.subTest(path=path):
                self.assertEqual(self.middleware_response(path).content, b"True")

    def test_invalidated_sessions_are_rejected_without_deleting_database_rows(self):
        self.user.set_password("changed-password")
        self.user.save(update_fields=("password",))
        for path in ("/admin/maintenance/", "/worker_maintenance"):
            with self.subTest(path=path):
                self.assertEqual(self.middleware_response(path).content, b"False")
                self.assertTrue(Session.objects.filter(session_key=self.session_key).exists())
