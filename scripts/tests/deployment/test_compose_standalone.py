"""One-file Compose portability and effective local/production contracts.

These checks render Compose configuration. They do not establish compatibility
with an unidentified Rancher/Azure installation or deploy any service.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from . import test_eea_storage_compose as storage


class ComposeStandaloneTests(storage._ComposeConfigCase):
    def test_local_configuration_does_not_require_production_images_or_credentials(self):
        model = self.model(profile="local", missing=("QC_TOOL_FRONTEND_IMAGE", "QC_TOOL_WORKER_IMAGE",
                                                    "DJANGO_SECRET_KEY", "QC_TOOL_POSTGRES_PASSWORD",
                                                    "QC_TOOL_PERSISTENT_ROOT", "QC_TOOL_PERSISTENT_STORAGE_ID"))
        services = model["services"]
        self.assertEqual(set(services), {"userdb", "frontend", "worker"})
        self.assert_role_boundaries(services)
        self.assertEqual(services["frontend"]["environment"]["QC_TOOL_ENVIRONMENT"], "development")
        self.assertEqual(services["frontend"]["environment"]["QC_TOOL_INITIALIZE_ON_STARTUP"], "yes")
        self.assertEqual(services["frontend"]["environment"]["QC_TOOL_BOOTSTRAP_DEMO_USERS"], "yes")
        for name in ("frontend", "worker"):
            self.assertIn("build", services[name])
            self.assertEqual(Path(services[name]["build"]["context"]), self.repository)
            self.assertTrue((self.repository / services[name]["build"]["dockerfile"]).is_file())
            source = self.mounts(services, name)["/usr/local/src/copernicus_quality_tools"]
            self.assertEqual(source["type"], "bind")
            self.assertEqual(Path(source["source"]), self.repository)
            self.assertTrue(source["read_only"])
            self.assertFalse(source["bind"].get("create_host_path", False))
        default = self.model(profile="local", project_name=None)
        self.assertEqual(default["name"], "copernicus-quality-tools-local")
        for key, volume in default["volumes"].items():
            self.assertEqual(volume["name"], "copernicus-quality-tools-local_" + key)

    def test_production_profiles_refuse_missing_or_empty_secrets_and_images(self):
        for profile in ("eea", "provider"):
            required = ["QC_TOOL_FRONTEND_IMAGE", "QC_TOOL_WORKER_IMAGE", "DJANGO_SECRET_KEY"]
            if profile == "eea":
                required.append("QC_TOOL_POSTGRES_PASSWORD")
            for key in required:
                for value in (None, ""):
                    with self.subTest(profile=profile, key=key, value=value):
                        options = {"missing": (key,)} if value is None else {"values": {key: value}}
                        result = self.render(profile=profile, persistent=False, **options)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(key, result.stderr)

    def test_postgres_profiles_preserve_dependencies_mount_identity_and_host_exposure(self):
        local = self.model(profile="local")
        production = self.model(persistent=False)
        self.assertEqual(set(local["volumes"]), set(production["volumes"]))
        self.assertEqual(set(local["volumes"]), {
            "postgres17_data_v3", "qc_tool_v3_boundaries", "qc_tool_v3_incoming",
            "qc_tool_v3_specifications", "qc_tool_v3_jobs", "qc_tool_v3_submissions",
            "qc_tool_v3_shared_state", "qc_tool_v3_frontend_state", "qc_tool_v3_worker_scratch",
            "qc_tool_v3_frontend_logs", "qc_tool_v3_worker_logs",
        })
        for model in (local, production):
            services = model["services"]
            self.assertEqual(services["frontend"]["depends_on"]["userdb"]["condition"], "service_healthy")
            self.assertEqual(services["worker"]["depends_on"]["frontend"]["condition"], "service_healthy")
            self.assertEqual(services["userdb"]["healthcheck"], local["services"]["userdb"]["healthcheck"])
            for name in ("frontend", "worker", "userdb"):
                expected = self.mounts(local["services"], name)
                if model is production and name != "userdb":
                    expected = {key: value for key, value in expected.items()
                                if key != "/usr/local/src/copernicus_quality_tools"}
                self.assertEqual(self.mounts(services, name), expected)
            self.assertEqual(services["frontend"]["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(local["services"]["userdb"]["ports"][0]["host_ip"], "127.0.0.1")
        self.assertNotIn("ports", production["services"]["userdb"])

    def test_sqlite_provider_does_not_inherit_a_phantom_postgres_dependency(self):
        services = self.model(profile="provider")["services"]
        self.assertEqual(set(services), {"frontend", "worker"})
        self.assertFalse(services["frontend"].get("depends_on"))
        frontend = services["frontend"]["environment"]
        self.assertEqual(frontend["DB_ENGINE"], "sqlite")
        self.assertEqual(frontend["SUBMISSION_DIR"], "")
        self.assertIsNone(self.application_paths(frontend)["submissions_dir"])
        self.assertFalse(frontend.get("QC_TOOL_INITIALIZE_ON_STARTUP"))
        self.assertFalse(frontend.get("QC_TOOL_BOOTSTRAP_DEMO_USERS"))
        self.assertEqual(services["worker"]["environment"]["RUN_INSPIRE_VALIDATOR"], "no")
        self.assertEqual(services["worker"]["environment"]["USE_LIGHTWEIGHT_VALIDATOR"], "yes")
        production = self.model(persistent=False)["services"]
        for name in ("frontend", "worker"):
            self.assertEqual(services[name]["healthcheck"], production[name]["healthcheck"])
        self.assertEqual(services["worker"]["depends_on"]["frontend"]["condition"], "service_healthy")

    def test_local_preview_database_overrides_do_not_redirect_eea(self):
        values = {"QC_TOOL_POSTGRES_DB": "isolated_preview", "QC_TOOL_POSTGRES_USER": "preview_user"}
        local = self.model(profile="local", values=values)["services"]
        production = self.model(persistent=False, values=values)["services"]
        for name in ("userdb", "frontend"):
            self.assertEqual(local[name]["environment"]["POSTGRES_DB"], "isolated_preview")
            self.assertEqual(local[name]["environment"]["POSTGRES_USER"], "preview_user")
            self.assertEqual(production[name]["environment"]["POSTGRES_DB"], "qc_tool")
            self.assertEqual(production[name]["environment"]["POSTGRES_USER"], "qc_user")

    def test_optional_configuration_is_forwarded_only_to_its_owning_roles(self):
        values = {
            "PRODUCT_DIRS": "/reviewed/specifications", "S3_ALLOWED_ENDPOINTS": "https://objects.example.invalid",
            "QC_TOOL_TRANSFER_MAX_RECORDS": "300000", "QC_TOOL_BACKUPS_DIR": "/var/lib/qc_tool/custom-backups",
            "S3_MAX_DOWNLOAD_BYTES": "1073741824", "LEAVE_JOBDIR": "yes",
        }
        for profile in ("local", "eea", "provider"):
            with self.subTest(profile=profile):
                services = self.model(profile=profile, persistent=False, values=values)["services"]
                for name in ("frontend", "worker"):
                    self.assertEqual(services[name]["environment"]["PRODUCT_DIRS"], values["PRODUCT_DIRS"])
                    self.assertEqual(services[name]["environment"]["S3_ALLOWED_ENDPOINTS"], values["S3_ALLOWED_ENDPOINTS"])
                frontend, worker = services["frontend"]["environment"], services["worker"]["environment"]
                self.assertEqual(frontend["QC_TOOL_TRANSFER_MAX_RECORDS"], values["QC_TOOL_TRANSFER_MAX_RECORDS"])
                self.assertEqual(frontend["QC_TOOL_BACKUPS_DIR"], values["QC_TOOL_BACKUPS_DIR"])
                self.assertNotIn("QC_TOOL_BACKUPS_DIR", worker)
                self.assertNotIn("QC_TOOL_TRANSFER_MAX_RECORDS", worker)
                self.assertEqual(worker["S3_MAX_DOWNLOAD_BYTES"], values["S3_MAX_DOWNLOAD_BYTES"])
                self.assertEqual(worker["LEAVE_JOBDIR"], "yes")
                self.assertNotIn("DJANGO_SECRET_KEY", worker)
                self.assertNotIn("POSTGRES_PASSWORD", worker)

    def test_profiles_have_no_external_composition_dependencies_or_custom_tags(self):
        for filename in ("compose.local.yaml", "docker-compose.eea.yml", "compose.eea-storage.yaml",
                         "docker-compose.service_provider.yml"):
            with self.subTest(profile=filename):
                source = (self.repository / "docker" / filename).read_text()
                self.assertNotRegex(source, r"(?m)^\s*(?:extends|include)\s*:")
                self.assertNotRegex(source, r"(?m)^\s*x-[\w-]+\s*:")
                self.assertNotIn("!override", source)
                self.assertNotIn("!reset", source)

    def test_production_profiles_render_from_a_single_copied_file(self):
        profiles = (("eea", False, "docker-compose.eea.yml"),
                    ("eea", True, "compose.eea-storage.yaml"),
                    ("provider", False, "docker-compose.service_provider.yml"))
        for profile, persistent, filename in profiles:
            with self.subTest(profile=filename), TemporaryDirectory(prefix="qc-compose-single-file-") as temporary:
                root = Path(temporary)
                selected = root / "compose.yaml"
                shutil.copyfile(self.repository / "docker" / filename, selected)
                result = subprocess.run([
                    self.docker, "compose", "--env-file", os.devnull,
                    "--project-name", "qc-eea-storage-test", "-f", str(selected),
                    "config", "--format", "json",
                ], cwd=root, env={**self.process_environment, **self.values},
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                isolated = json.loads(result.stdout)
                original = self.model(profile=profile, persistent=persistent)
                self.assertEqual(isolated, original)
                self.assert_role_boundaries(isolated["services"])
                self.assertEqual(list(root.iterdir()), [selected])
                self.assertFalse(self.mount.exists())
