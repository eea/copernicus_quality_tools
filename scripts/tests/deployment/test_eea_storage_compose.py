"""Render persistent-storage deployment contracts without starting services.

Docker Compose is optional for the offline test runner. These tests call only
``config`` with synthetic credentials and an empty environment file; they do not
contact the Docker daemon or load the repository's private deployment settings.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


class EEAStorageComposeTests(unittest.TestCase):
    repository = Path(__file__).resolve().parents[3]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        docker = shutil.which("docker")
        if not docker:
            raise unittest.SkipTest("Docker Compose 2.24.4+ is required for config-only checks")
        # Do not inherit application credentials or COMPOSE_* settings from the
        # operator's shell. Compose config does not need a daemon connection.
        cls.process_environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "SYSTEMROOT", "DOCKER_CONFIG")
            if key in os.environ
        }
        version = subprocess.run(
            [docker, "compose", "version", "--short"],
            env=cls.process_environment, text=True, capture_output=True, timeout=15,
        )
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", version.stdout)
        if version.returncode or not match or tuple(map(int, match.groups())) < (2, 24, 4):
            raise unittest.SkipTest("Docker Compose 2.24.4+ is required for !override")
        cls.docker = docker

    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-eea-compose-")
        self.addCleanup(temporary.cleanup)
        self.mount = Path(temporary.name) / "unprovisioned-persistent-mount"
        self.values = {
            "QC_TOOL_FRONTEND_IMAGE": "example.invalid/frontend@sha256:" + "a" * 64,
            "QC_TOOL_WORKER_IMAGE": "example.invalid/worker@sha256:" + "b" * 64,
            "QC_TOOL_POSTGRES_PASSWORD": "synthetic-postgres-test-value",
            "DJANGO_SECRET_KEY": "synthetic-django-test-value",
            "PRODUCT_DIRS": "/usr/local/src/copernicus_quality_tools/product_definitions",
            "QC_TOOL_PERSISTENT_ROOT": str(self.mount),
            "QC_TOOL_PERSISTENT_STORAGE_ID": "eea-compose-test-storage",
        }

    def render(self, *, persistent=True, values=None, missing=()):
        environment = {**self.process_environment, **self.values, **(values or {})}
        for key in missing:
            environment.pop(key, None)
        arguments = [self.docker, "compose", "--env-file", os.devnull,
                     "--project-name", "qc-eea-storage-test",
                     "-f", "docker/docker-compose.eea.yml"]
        if persistent:
            arguments.extend(["-f", "docker/compose.eea-storage.yaml"])
        arguments.extend(["config", "--format", "json"])
        result = subprocess.run(arguments, cwd=self.repository, env=environment,
                                text=True, capture_output=True, timeout=30)
        self.assertFalse(self.mount.exists(), "Rendering must not provision host storage")
        return result

    def model(self, **options):
        result = self.render(**options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_base_eea_deployment_keeps_existing_named_volumes(self):
        services = self.model(persistent=False)["services"]
        expected = {
            "userdb": {"/var/lib/postgresql/data": "postgres_data"},
            "frontend": {
                "/mnt/qc_tool_boundary": "qc_tool_boundary",
                "/mnt/qc_tool_incoming": "qc_tool_incoming",
                "/mnt/qc_tool_submission": "qc_tool_submission",
                "/mnt/qc_tool_work": "qc_tool_work",
                "/var/lib/qc_tool": "qc_tool_frontend",
            },
            "worker": {
                "/mnt/qc_tool_boundary": "qc_tool_boundary",
                "/mnt/qc_tool_incoming": "qc_tool_incoming",
                "/mnt/qc_tool_work": "qc_tool_work",
            },
        }
        for service, mounts in expected.items():
            with self.subTest(service=service):
                volumes = services[service]["volumes"]
                self.assertEqual({item["target"]: item["source"] for item in volumes}, mounts)
                self.assertTrue(all(item["type"] == "volume" for item in volumes))
        for service in ("frontend", "worker"):
            self.assertNotIn("QC_TOOL_PERSISTENT_STORAGE_ROOT", services[service]["environment"])

    def test_override_replaces_child_volumes_with_the_same_persistent_tree(self):
        services = self.model()["services"]
        expected = {
            "userdb": {"/var/lib/postgresql/data": self.mount / "private/postgresql"},
            "frontend": {"/mnt": self.mount / "data",
                         "/var/lib/qc_tool": self.mount / "private/frontend"},
            "worker": {"/mnt": self.mount / "data"},
        }
        for service, mounts in expected.items():
            with self.subTest(service=service):
                volumes = services[service]["volumes"]
                self.assertEqual({item["target"]: item["source"] for item in volumes},
                                 {target: str(source) for target, source in mounts.items()})
                for item in volumes:
                    self.assertEqual(item["type"], "bind")
                    self.assertFalse(item["bind"].get("create_host_path", False))
                    self.assertFalse(item.get("read_only", False))
        # Nested named mounts would hide the host directories and split the
        # frontend/worker view of files despite the top-level bind mount.
        for service in ("frontend", "worker"):
            self.assertFalse(any(item["target"].startswith("/mnt/")
                                 for item in services[service]["volumes"]))
            environment = services[service]["environment"]
            self.assertEqual(environment["QC_TOOL_PERSISTENT_STORAGE_ROOT"], "/mnt")
            self.assertEqual(environment["QC_TOOL_PERSISTENT_STORAGE_ID"], self.values["QC_TOOL_PERSISTENT_STORAGE_ID"])
            self.assertEqual(environment["QC_TOOL_MAINTENANCE_DIR"], "/mnt/qc_tool_work/work/maintenance")
        # The browser sees only data/. Private database bytes are absent from
        # both app containers, and frontend state has its own non-browser mount.
        for service in ("frontend", "worker"):
            self.assertNotIn(str(self.mount / "private/postgresql"),
                             {item["source"] for item in services[service]["volumes"]})
        frontend_private = next(item for item in services["frontend"]["volumes"]
                                if item["source"] == str(self.mount / "private/frontend"))
        self.assertEqual(frontend_private["target"], "/var/lib/qc_tool")

    def test_container_paths_credentials_and_image_pair_are_preserved(self):
        baseline, persistent = self.model(persistent=False), self.model()
        permitted = {
            "frontend": {"QC_TOOL_PERSISTENT_STORAGE_ROOT", "QC_TOOL_PERSISTENT_STORAGE_ID",
                         "S3_CREDENTIALS_DIR", "QC_TOOL_UPLOAD_TEMP_DIR", "QC_TOOL_MAINTENANCE_DIR"},
            "worker": {"QC_TOOL_PERSISTENT_STORAGE_ROOT", "QC_TOOL_PERSISTENT_STORAGE_ID",
                       "QC_TOOL_MAINTENANCE_DIR"},
            "userdb": set(),
        }
        for name in ("frontend", "worker", "userdb"):
            with self.subTest(service=name):
                before, after = baseline["services"][name], persistent["services"][name]
                self.assertEqual(before["image"], after["image"])
                self.assertEqual(before.get("depends_on"), after.get("depends_on"))
                self.assertEqual(before.get("healthcheck"), after.get("healthcheck"))
                self.assertEqual({key: value for key, value in before["environment"].items()
                                  if key not in permitted[name]},
                                 {key: value for key, value in after["environment"].items()
                                  if key not in permitted[name]})
        environment = persistent["services"]["frontend"]["environment"]
        self.assertEqual(environment["S3_CREDENTIALS_DIR"], "/mnt/qc_tool_work/work/s3_credentials")
        self.assertEqual(environment["QC_TOOL_UPLOAD_TEMP_DIR"], "/mnt/qc_tool_work/work/upload-staging")
        self.assertEqual(environment["QC_TOOL_TRANSFER_DIR"], "/mnt/qc_tool_work/work/data-transfer")

    def test_explicit_private_directory_overrides_remain_supported(self):
        values = {
            "S3_CREDENTIALS_DIR": "/mnt/qc_tool_work/work/private/credentials",
            "QC_TOOL_UPLOAD_TEMP_DIR": "/mnt/qc_tool_work/work/private/staging",
            "QC_TOOL_TRANSFER_DIR": "/mnt/qc_tool_work/work/private/transfers",
            "QC_TOOL_MAINTENANCE_DIR": "/mnt/qc_tool_work/work/private/maintenance",
        }
        services = self.model(values=values)["services"]
        for key, expected in values.items():
            self.assertEqual(services["frontend"]["environment"][key], expected)
        self.assertEqual(services["worker"]["environment"]["QC_TOOL_MAINTENANCE_DIR"],
                         values["QC_TOOL_MAINTENANCE_DIR"])

    def test_storage_root_and_identity_are_required_without_local_fallback(self):
        for key in ("QC_TOOL_PERSISTENT_ROOT", "QC_TOOL_PERSISTENT_STORAGE_ID"):
            for value in (None, ""):
                with self.subTest(variable=key, value=value):
                    options = {"missing": (key,)} if value is None else {"values": {key: value}}
                    result = self.render(**options)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(key, result.stderr)


if __name__ == "__main__":
    unittest.main()
