"""Execute startup and Supervisor locally, without QC data or external services."""

import configparser
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest


class WorkerEntrypointTests(unittest.TestCase):
    repository = Path(__file__).resolve().parents[3]

    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="qcj-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # The runtime gate is separately exercised against the real worker image.
        # Leave Python itself real for the argument serialization under test.
        self.executable("python3", "#!/bin/bash\n"
                        'if [[ "$1" == */docker/check_worker_runtime.py ]]; then exit 0; fi\n'
                        f"exec {shlex.quote(sys.executable)} \"$@\"\n")
        self.executable("chown", "#!/bin/sh\nexit 0\n")
        source = (self.repository / "docker/inspire/docker-entrypoint.sh").read_text()
        # Sandbox only fixed container paths; execute all startup logic unchanged.
        for container_path in (
            "/run/qc-tool-wgetrc", "/etc/squid_hosts", "/var/run/squid.pid",
            "/var/run/apache2/apache2.pid",
        ):
            source = source.replace(container_path, str(self.root / Path(container_path).name))
        self.entrypoint = self.root / "entrypoint.sh"
        self.entrypoint.write_text(source)
        self.environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ.get('PATH', '')}",
            "ETF_DIR": str(self.root / "etf"),
            "JAVA_MAX_MEM": "1536",
            "HTTP_PROXY_HOST": "localhost", "HTTP_PROXY_PORT": "3128",
            "HTTP_PROXY_USERNAME": "", "HTTP_PROXY_PASSWORD": "",
            "HTTPS_PROXY_HOST": "none", "HTTPS_PROXY_PORT": "3129",
            "HTTPS_PROXY_USERNAME": "", "HTTPS_PROXY_PASSWORD": "",
            "RUN_INSPIRE_VALIDATOR": "yes",
        }
        self.environment.pop("JAVA_OPTIONS", None)

    def executable(self, name, source):
        path = self.bin / name
        path.write_text(source)
        path.chmod(0o755)
        return path

    def capture_options(self, **environment):
        capture = self.root / "options.json"
        result = subprocess.run(
            ["bash", str(self.entrypoint), sys.executable, "-c",
             "import json,os,sys; "
             "json.dump(os.environ['JAVA_OPTIONS'], open(sys.argv[1], 'w'))", str(capture)],
            env={**self.environment, **environment}, text=True, capture_output=True,
            timeout=10,
        )
        return result, json.loads(capture.read_text()) if capture.exists() else None

    def test_default_budget_and_proxy_are_exported_as_java_arguments(self):
        result, options = self.capture_options()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split(options), [
            "-server", "-Xms1g", "-Xmx1572864k",
            "-Dhttp.proxyHost=localhost", "-Dhttp.proxyPort=3128",
        ])
        self.assertEqual((self.root / "qc-tool-wgetrc").stat().st_mode & 0o777, 0o600)

    def test_explicit_budget_with_disabled_proxies(self):
        result, options = self.capture_options(JAVA_MAX_MEM="2048", HTTP_PROXY_HOST="none")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shlex.split(options), ["-server", "-Xms1g", "-Xmx2097152k"])

    def test_invalid_budget_refuses_startup_before_exec(self):
        for value in ("512", "not-a-number"):
            with self.subTest(value=value):
                result, options = self.capture_options(JAVA_MAX_MEM=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(options)

    def test_disabled_validator_does_not_execute_java(self):
        marker = self.root / "disabled-sleep"
        self.executable("sleep", f"#!/bin/sh\nprintf '%s' \"$1\" > {shlex.quote(str(marker))}\n")
        result = subprocess.run(
            ["bash", str(self.repository / "docker/start_optional_service.sh"),
             "Validator", "does-not-exist-java"],
            env={**self.environment, "RUN_INSPIRE_VALIDATOR": "no"},
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), "infinity")

    @unittest.skipUnless(importlib.util.find_spec("supervisor"), "requires Supervisor 4.3")
    def test_real_supervisor_preserves_proxy_argv_and_client_needs_no_exported_options(self):
        username = "proxy user 'quoted' 100% %(ENV_DO_NOT_EXPAND)s"
        password = 'secret "double" \'single\' ; $literal $(never-execute) 50%'
        self.environment.update({
            "JAVA_MAX_MEM": "2048", "HTTP_PROXY_USERNAME": username,
            "HTTP_PROXY_PASSWORD": password, "HTTPS_PROXY_HOST": "secure-proxy",
            "HTTPS_PROXY_PORT": "8443", "HTTPS_PROXY_USERNAME": username,
            "HTTPS_PROXY_PASSWORD": password,
        })
        capture = self.root / "java-argv.json"
        java = self.root / "fake_java.py"
        java.write_text("import json,sys,time\n"
                        f"json.dump(sys.argv[1:], open({str(capture)!r}, 'w'))\n"
                        "time.sleep(30)\n")
        original = configparser.RawConfigParser()
        original.read(self.repository / "docker/supervisord.conf")
        command = original.get("program:inspirevalidator", "command")
        wrapper = self.executable("start_optional_service.sh", (
            self.repository / "docker/start_optional_service.sh").read_text())
        command = command.replace("/usr/local/bin/start_optional_service.sh",
                                  shlex.quote(str(wrapper)))
        command = command.replace(" java ", f" {shlex.quote(sys.executable)} {shlex.quote(str(java))} ")
        socket = self.root / "s"
        configuration = self.root / "supervisord.conf"
        configuration.write_text(
            f"[unix_http_server]\nfile={socket}\nchmod=0700\n"
            "[rpcinterface:supervisor]\n"
            "supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface\n"
            f"[supervisord]\nnodaemon=true\nlogfile={self.root / 'supervisor.log'}\n"
            f"pidfile={self.root / 'supervisor.pid'}\nchildlogdir={self.root}\n"
            f"[supervisorctl]\nserverurl=unix://{socket}\n"
            f"[program:inspirevalidator]\ncommand={command}\nstartsecs=0\n"
            "autorestart=false\nstopwaitsecs=1\nstopsignal=TERM\n"
        )
        process = subprocess.Popen(
            ["bash", str(self.entrypoint), sys.executable, "-m", "supervisor.supervisord",
             "-c", str(configuration)],
            env=self.environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not capture.exists() and process.poll() is None:
                time.sleep(0.05)
            self.assertTrue(capture.exists(), "Supervisor did not execute the validator command")
            self.assertEqual(json.loads(capture.read_text()), [
                "-Djava.io.tmpdir=/tmp/jetty", "-server", "-Xms1g", "-Xmx2097152k",
                "-Dhttp.proxyHost=localhost", "-Dhttp.proxyPort=3128",
                f"-Dhttp.proxyUser={username}", f"-Dhttp.proxyPassword={password}",
                "-Dhttps.proxyHost=secure-proxy", "-Dhttps.proxyPort=8443",
                f"-Dhttps.proxyUser={username}", f"-Dhttps.proxyPassword={password}",
                "-jar", "/usr/local/jetty/start.jar",
            ])
            # docker exec gets the image environment, not exports from entrypoint.
            client_environment = {**self.environment}
            client_environment.pop("JAVA_OPTIONS", None)
            client = subprocess.run(
                [sys.executable, "-m", "supervisor.supervisorctl", "-c", str(configuration),
                 "status", "inspirevalidator"], env=client_environment,
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(client.returncode, 0, client.stderr)
            self.assertIn("RUNNING", client.stdout)
        finally:
            process.terminate()
            output, _ = process.communicate(timeout=10)
        self.assertNotIn(username, output)
        self.assertNotIn(password, output)
        logs = (self.root / "supervisor.log").read_text()
        self.assertNotIn(username, logs)
        self.assertNotIn(password, logs)


if __name__ == "__main__":
    unittest.main()
