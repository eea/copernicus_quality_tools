"""Verify frontend startup without application data or database access."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen


class FrontendEntrypointTests(unittest.TestCase):
    repository = Path(__file__).resolve().parents[3]

    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-frontend-entrypoint-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        executable_directory = self.root / "bin"
        executable_directory.mkdir()
        self.log = self.root / "commands.log"
        stub = (
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$QC_FRONTEND_TEST_LOG"\n'
            'if [ "$*" = "-m qc_tool.storage check" ]; then\n'
            '    exit "${QC_FRONTEND_TEST_STORAGE_FAILURE:-0}"\n'
            'fi\n'
            'if [ "$*" = "-m qc_tool.frontend.manage database check --allow-maintenance-recovery" ]; then\n'
            '    printf "%s\\n" ready\n'
            'fi\n'
        )
        for name in ("python3", "gunicorn"):
            executable = executable_directory / name
            executable.write_text(stub)
            executable.chmod(0o755)
        # Replace only the image's fixed working directory. All production
        # startup decisions still execute, with external commands captured.
        source = (self.repository / "docker/run_frontend.sh").read_text().replace(
            "cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend",
            'cd "$QC_FRONTEND_TEST_DIRECTORY"',
        )
        self.entrypoint = self.root / "entrypoint.sh"
        self.entrypoint.write_text(source)
        self.environment = {
            **os.environ,
            "PATH": f"{executable_directory}:{os.environ.get('PATH', '')}",
            "QC_FRONTEND_TEST_LOG": str(self.log),
            "QC_FRONTEND_TEST_DIRECTORY": str(self.root),
            "QC_TOOL_ENVIRONMENT": "production",
            "QC_TOOL_INITIALIZE_ON_STARTUP": "no",
            "QC_TOOL_BOOTSTRAP_DEMO_USERS": "no",
            "QC_TOOL_DEV_SERVER": "no",
            "QC_TOOL_WEB_WORKERS": "1",
            "QC_TOOL_WEB_TIMEOUT_SECONDS": "120",
        }
        self.environment.pop("QC_TOOL_MIGRATE_ON_STARTUP", None)
        self.environment.pop("GUNICORN_CMD_ARGS", None)
        self.environment.pop("QC_TOOL_PERSISTENT_STORAGE_ROOT", None)
        self.environment.pop("QC_TOOL_PERSISTENT_STORAGE_ID", None)

    def startup(self, **environment):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(
            ["sh", str(self.entrypoint)],
            env={**self.environment, **environment}, text=True, capture_output=True,
            timeout=10,
        )
        commands = self.log.read_text().splitlines() if self.log.exists() else []
        return result, commands

    def gunicorn_arguments(self):
        result, commands = self.startup()
        self.assertEqual(result.returncode, 0, result.stderr)
        return shlex.split(commands[-1])

    def test_production_checks_readiness_then_uses_one_threaded_process(self):
        result, commands = self.startup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[:2], [
            "-m qc_tool.frontend.manage database check --allow-maintenance-recovery",
            "-m qc_tool.frontend.manage collectstatic --noinput",
        ])
        self.assertEqual(len(commands), 3)
        self.assertEqual(shlex.split(commands[-1]), [
            "--bind", "0.0.0.0:8000", "--workers", "1",
            "--worker-class", "gthread", "--threads", "4",
            "--timeout", "120", "qc_tool.frontend.wsgi:application",
        ])
        self.assertNotIn("--preload", commands[-1])
        self.assertFalse(any("database apply" in command for command in commands))

    def test_unsupported_process_counts_fail_before_any_database_command(self):
        for count in ("0", "2", "-1", "many"):
            with self.subTest(workers=count):
                result, commands = self.startup(QC_TOOL_WEB_WORKERS=count)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(commands, [])
                self.assertIn("QC_TOOL_WEB_WORKERS must be 1", result.stderr)

    def test_configured_persistence_is_checked_before_django_commands(self):
        result, commands = self.startup(
            QC_TOOL_PERSISTENT_STORAGE_ROOT="/mnt",
            QC_TOOL_PERSISTENT_STORAGE_ID="test-installation",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[:3], [
            "-m qc_tool.storage check",
            "-m qc_tool.frontend.manage database check --allow-maintenance-recovery",
            "-m qc_tool.frontend.manage collectstatic --noinput",
        ])

    def test_storage_failure_and_partial_configuration_stop_before_django(self):
        for configuration in (
            {"QC_TOOL_PERSISTENT_STORAGE_ROOT": "/mnt"},
            {"QC_TOOL_PERSISTENT_STORAGE_ID": "test-installation"},
            {"QC_TOOL_PERSISTENT_STORAGE_ROOT": ""},
        ):
            with self.subTest(configuration=configuration):
                result, commands = self.startup(
                    **configuration, QC_FRONTEND_TEST_STORAGE_FAILURE="1",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(commands, ["-m qc_tool.storage check"])

    def test_existing_worker_heartbeat_override_remains_supported(self):
        result, commands = self.startup(QC_TOOL_WEB_TIMEOUT_SECONDS="240")
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = shlex.split(commands[-1])
        self.assertEqual(arguments[arguments.index("--timeout") + 1], "240")
        self.assertEqual(arguments[arguments.index("--threads") + 1], "4")

    @unittest.skipUnless(importlib.util.find_spec("gunicorn"), "requires frontend Gunicorn runtime")
    def test_real_threaded_server_keeps_health_responsive_during_a_slow_request(self):
        marker = self.root / "slow-request-started"
        (self.root / "runtime_probe.py").write_text(
            "from pathlib import Path\nimport time\n"
            "def application(environ, start_response):\n"
            "    if environ['PATH_INFO'] == '/slow':\n"
            f"        Path({str(marker)!r}).touch()\n"
            "        time.sleep(2)\n"
            "    start_response('200 OK', [('Content-Type', 'text/plain')])\n"
            "    return [b'ok']\n"
        )
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        arguments = self.gunicorn_arguments()
        arguments[arguments.index("--bind") + 1] = f"127.0.0.1:{port}"
        arguments[-1] = "runtime_probe:application"
        environment = {**os.environ}
        environment.pop("GUNICORN_CMD_ARGS", None)
        with (self.root / "gunicorn.log").open("w+") as output:
            process = subprocess.Popen(
                [sys.executable, "-m", "gunicorn", *arguments],
                cwd=self.root, env=environment, stdout=output, stderr=subprocess.STDOUT,
            )
            try:
                base = f"http://127.0.0.1:{port}"

                def get(path, timeout=5):
                    with urlopen(base + path, timeout=timeout) as response:
                        return response.read()

                deadline = time.monotonic() + 10
                while True:
                    try:
                        self.assertEqual(get("/health", timeout=0.2), b"ok")
                        break
                    except (URLError, TimeoutError):
                        if process.poll() is not None or time.monotonic() >= deadline:
                            output.seek(0)
                            self.fail("Threaded server did not start: " + output.read())
                        time.sleep(0.05)
                with ThreadPoolExecutor(max_workers=1) as executor:
                    slow = executor.submit(get, "/slow")
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists(), "Slow request was not admitted")
                    self.assertFalse(slow.done())
                    self.assertEqual(get("/health", timeout=1), b"ok")
                    self.assertFalse(slow.done(), "Health waited for the slow request")
                    self.assertEqual(slow.result(timeout=5), b"ok")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
