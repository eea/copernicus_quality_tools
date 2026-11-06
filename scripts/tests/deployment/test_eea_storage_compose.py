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
import sys
from tempfile import TemporaryDirectory
import unittest


class _ComposeConfigCase(unittest.TestCase):
    repository = Path(__file__).resolve().parents[3]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        docker = shutil.which("docker")
        if not docker:
            raise unittest.SkipTest("Docker Compose v2 is required for config-only checks")
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
        if version.returncode or not match or int(match.group(1)) < 2:
            raise unittest.SkipTest("Docker Compose v2 is required for config-only checks")
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

    def render(self, *, profile="eea", persistent=None, project_name="qc-eea-storage-test", values=None, missing=()):
        environment = {**self.process_environment, **self.values, **(values or {})}
        for key in missing:
            environment.pop(key, None)
        if persistent is None:
            persistent = profile == "eea"
        filename = {"local": "compose.local.yaml",
                    "eea": "compose.eea-storage.yaml" if persistent else "docker-compose.eea.yml",
                    "provider": "docker-compose.service_provider.yml"}[profile]
        arguments = [self.docker, "compose", "--env-file", os.devnull]
        if project_name is not None:
            arguments.extend(["--project-name", project_name])
        arguments.extend(["-f", "docker/" + filename])
        arguments.extend(["config", "--format", "json"])
        result = subprocess.run(arguments, cwd=self.repository, env=environment,
                                text=True, capture_output=True, timeout=30)
        self.assertFalse(self.mount.exists(), "Rendering must not provision host storage")
        return result

    def model(self, **options):
        result = self.render(**options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def mounts(self, services, name):
        return {item["target"]: item for item in services[name]["volumes"]}

    def application_paths(self, environment):
        """Resolve omitted profile defaults through the owning stdlib module."""
        process_environment = {**self.process_environment,
                               **{key: value for key, value in environment.items() if value is not None},
                               "PYTHONPATH": str(self.repository / "src")}
        result = subprocess.run([
            sys.executable, "-c",
            "from dataclasses import asdict; import json; "
            "from qc_tool.storage.layout import layout_config,runtime_paths; "
            "print(json.dumps({key:str(value) if value is not None else None "
            "for key,value in asdict(runtime_paths(layout_config())).items()}))",
        ], env=process_environment, cwd=self.repository, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_role_boundaries(self, services):
        data = "/mnt/qc-tool/data"
        for name in ("frontend", "worker"):
            environment = services[name]["environment"]
            self.assertEqual(environment["QC_TOOL_DATA_ROOT"], data)
            self.assertEqual(environment["QC_TOOL_STORAGE_ROLE"], name)
            self.assertEqual(environment["QC_TOOL_REQUIRE_MOUNTS"], "yes")
            paths = self.application_paths(environment)
            self.assertEqual(paths["jobs_dir"], data + "/jobs")
            self.assertEqual(paths["shared_state_dir"], "/mnt/qc-tool/state/shared")
            self.assertEqual(paths["logs_dir"], "/var/log/qc-tool")
            mounts = self.mounts(services, name)
            self.assertNotIn("/mnt", mounts)
            self.assertNotIn("/mnt/qc-tool", mounts)
            self.assertNotIn(data, mounts)
            self.assertFalse(mounts[data + "/jobs"].get("read_only", False))
            self.assertFalse(mounts["/mnt/qc-tool/state/shared"].get("read_only", False))
        worker = self.mounts(services, "worker")
        for area in ("incoming", "boundaries", "specifications"):
            self.assertTrue(worker[data + "/" + area]["read_only"])
        for private in ("/var/lib/qc_tool", data + "/submissions"):
            self.assertNotIn(private, worker)
        self.assertIn("/var/tmp/qc-tool/jobs", worker)
        frontend = self.mounts(services, "frontend")
        self.assertIn("/var/lib/qc_tool", frontend)
        self.assertNotIn("/var/tmp/qc-tool/jobs", frontend)
        self.assertNotEqual(frontend["/var/log/qc-tool"]["source"], worker["/var/log/qc-tool"]["source"])


class EEAStorageComposeTests(_ComposeConfigCase):
    def test_base_eea_uses_fresh_separated_volumes_and_postgres17(self):
        services = self.model(persistent=False)["services"]
        self.assert_role_boundaries(services)
        self.assertEqual(services["userdb"]["image"], "postgres:17")
        self.assertEqual(self.mounts(services, "userdb")["/var/lib/postgresql/data"]["source"], "postgres17_data_v3")
        for name in ("frontend", "worker"):
            self.assertNotIn("QC_TOOL_PERSISTENT_STORAGE_ROOT", services[name]["environment"])
            self.assertTrue(all(item["type"] == "volume" for item in services[name]["volumes"]))
            self.assertTrue(all(item["source"].startswith("qc_tool_v3_") for item in services[name]["volumes"]))

    def test_host_profile_preserves_narrow_mounts_without_provisioning_or_parent_binds(self):
        services = self.model()["services"]
        self.assert_role_boundaries(services)
        for name in ("frontend", "worker", "userdb"):
            for item in services[name]["volumes"]:
                self.assertEqual(item["type"], "bind")
                self.assertFalse(item["bind"].get("create_host_path", False))
                self.assertTrue(Path(item["source"]).is_relative_to(self.mount))
        for name in ("frontend", "worker"):
            environment = services[name]["environment"]
            self.assertEqual(environment["QC_TOOL_PERSISTENT_STORAGE_ROOT"], "/mnt/qc-tool/data")
            self.assertEqual(environment["QC_TOOL_PERSISTENT_STORAGE_ID"], self.values["QC_TOOL_PERSISTENT_STORAGE_ID"])
            for area in ("incoming", "boundaries", "specifications", "jobs"):
                self.assertEqual(self.mounts(services, name)["/mnt/qc-tool/data/" + area]["source"], str(self.mount / "data" / area))
        self.assertEqual(self.mounts(services, "frontend")["/var/lib/qc_tool"]["source"], str(self.mount / "private/frontend"))
        self.assertEqual(self.mounts(services, "worker")["/var/tmp/qc-tool/jobs"]["source"], str(self.mount / "scratch/worker"))
        self.assertEqual(self.mounts(services, "userdb")["/var/lib/postgresql/data"]["source"], str(self.mount / "private/postgresql17"))

    def test_host_profile_preserves_images_connections_and_private_paths(self):
        baseline, persistent = self.model(persistent=False), self.model()
        for name in ("frontend", "worker", "userdb"):
            before, after = baseline["services"][name], persistent["services"][name]
            for key in ("image", "depends_on", "healthcheck"):
                self.assertEqual(before.get(key), after.get(key))
            permitted = {"QC_TOOL_PERSISTENT_STORAGE_ROOT", "QC_TOOL_PERSISTENT_STORAGE_ID"}
            self.assertEqual({key: value for key, value in before["environment"].items() if key not in permitted},
                             {key: value for key, value in after["environment"].items() if key not in permitted})
        environment = persistent["services"]["frontend"]["environment"]
        paths = self.application_paths(environment)
        self.assertEqual(environment["S3_CREDENTIALS_DIR"], "/var/lib/qc_tool/s3_credentials")
        self.assertEqual(paths["upload_temp_dir"], "/var/lib/qc_tool/upload-staging")
        self.assertEqual(paths["transfer_dir"], "/var/lib/qc_tool/data-transfer")
        self.assertEqual(paths["backups_dir"], "/var/lib/qc_tool/backups")
        self.assertEqual(environment.get("FRONTEND_DB_PATH") or "/var/lib/qc_tool/frontend.sqlite3",
                         "/var/lib/qc_tool/frontend.sqlite3")

    def test_local_and_service_provider_use_the_same_role_boundaries(self):
        for filename in ("compose.local.yaml", "docker-compose.service_provider.yml"):
            with self.subTest(profile=filename):
                environment = {**self.process_environment, **self.values}
                result = subprocess.run([self.docker, "compose", "--env-file", os.devnull,
                                         "--project-name", "qc-layout-test", "-f", "docker/" + filename,
                                         "config", "--format", "json"], cwd=self.repository,
                                        env=environment, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                services = json.loads(result.stdout)["services"]
                self.assert_role_boundaries(services)
                if filename == "docker-compose.service_provider.yml":
                    self.assertEqual(services["frontend"]["environment"]["SUBMISSION_DIR"], "")
                    self.assertNotIn("QC_TOOL_INITIALIZE_ON_STARTUP", services["frontend"]["environment"])
                else:
                    self.assertEqual(services["frontend"]["environment"]["QC_TOOL_INITIALIZE_ON_STARTUP"], "yes")

    def test_explicit_private_directory_overrides_remain_on_private_mount(self):
        values = {"S3_CREDENTIALS_DIR": "/var/lib/qc_tool/custom-credentials",
                  "QC_TOOL_UPLOAD_TEMP_DIR": "/var/lib/qc_tool/custom-staging",
                  "QC_TOOL_TRANSFER_DIR": "/var/lib/qc_tool/custom-transfers"}
        services = self.model(values=values)["services"]
        for key, expected in values.items():
            self.assertEqual(services["frontend"]["environment"][key], expected)
            self.assertNotIn(key, services["worker"]["environment"])

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
