"""Recovery commands expose readiness reliably to operators and shell scripts."""

from io import StringIO
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.management.commands.maintenance import Command
from qc_tool.frontend.dashboard.services import maintenance


class MaintenanceCommandTests(SimpleTestCase):
    def setUp(self):
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.command = Command(stdout=self.stdout, stderr=self.stderr)

    def status(self, phase="stopping", generation=5):
        return {
            "enabled": phase != "off", "phase": phase,
            "generation": generation, "blockers": [],
        }

    def run_command(self, *arguments):
        return self.command.run_from_argv(["manage", "maintenance", *arguments])

    def test_pending_on_and_check_emit_state_and_exit_nonzero(self):
        for action in ("on", "check"):
            with self.subTest(action=action):
                self.stdout.seek(0)
                self.stdout.truncate()
                self.stderr.seek(0)
                self.stderr.truncate()
                with (
                    patch.object(maintenance, "read_status", return_value=self.status()),
                    patch.object(maintenance, "enable", return_value=self.status()),
                    patch.object(maintenance, "advance", return_value=self.status()),
                    self.assertRaises(SystemExit) as error,
                ):
                    self.run_command(action)

                self.assertEqual(error.exception.code, 1)
                self.assertEqual(json.loads(self.stdout.getvalue())["phase"], "stopping")
                self.assertIn("work has not stopped", self.stderr.getvalue())

    def test_ready_check_succeeds_with_machine_readable_state(self):
        with (
            patch.object(maintenance, "read_status", return_value=self.status()),
            patch.object(maintenance, "advance", return_value=self.status("ready")) as advance,
        ):
            self.run_command("check", "--generation", "5")

        advance.assert_called_once_with(5)
        self.assertEqual(json.loads(self.stdout.getvalue())["phase"], "ready")
        self.assertEqual(self.stderr.getvalue(), "")

    def test_status_skips_application_system_checks_for_recovery(self):
        with (
            patch.object(maintenance, "read_status", return_value=self.status()),
            patch.object(self.command, "check", side_effect=AssertionError("schema unavailable")),
        ):
            self.run_command("status")

        self.assertEqual(json.loads(self.stdout.getvalue())["generation"], 5)

    def test_retirement_requires_explicit_generation_and_operator_attestation(self):
        incomplete_arguments = (
            ("retire-worker",),
            ("retire-worker", "--worker-url", "http://127.0.0.1:8000/", "--generation", "5"),
            ("retire-worker", "--worker-url", "http://127.0.0.1:8000/", "--verified-stopped"),
        )
        with (
            patch.object(maintenance, "retire_worker") as retire_worker,
            patch.object(maintenance, "read_status") as read_status,
        ):
            for arguments in incomplete_arguments:
                with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as error:
                    self.run_command(*arguments)
                self.assertEqual(error.exception.code, 1)

        retire_worker.assert_not_called()
        read_status.assert_not_called()

    def test_attested_retirement_delegates_to_the_shared_service(self):
        with patch.object(maintenance, "retire_worker", return_value=self.status(generation=6)) as retire_worker:
            self.run_command(
                "retire-worker", "--worker-url", "http://127.0.0.1:8000/",
                "--generation", "5", "--verified-stopped",
            )

        retire_worker.assert_called_once_with(
            "http://127.0.0.1:8000/", "operator command", 5,
            verified_stopped=True,
        )
        self.assertEqual(json.loads(self.stdout.getvalue())["generation"], 6)

    def test_negative_generation_is_rejected_before_reading_state(self):
        with (
            patch.object(maintenance, "read_status") as read_status,
            self.assertRaises(SystemExit) as error,
        ):
            self.run_command("off", "--generation", "-1")

        self.assertEqual(error.exception.code, 1)
        read_status.assert_not_called()

    def test_service_failure_exits_nonzero_with_safe_error(self):
        with (
            patch.object(maintenance, "read_status", side_effect=maintenance.MaintenanceError("Maintenance storage is unavailable.")),
            self.assertRaises(SystemExit) as error,
        ):
            self.run_command("status")

        self.assertEqual(error.exception.code, 1)
        self.assertIn("Maintenance storage is unavailable.", self.stderr.getvalue())
        self.assertNotIn("Traceback", self.stderr.getvalue())
