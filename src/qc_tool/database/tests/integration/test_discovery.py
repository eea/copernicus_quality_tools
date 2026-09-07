"""Django discovers the unchanged schema identities from the central package."""

from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from django.apps import apps
from django.conf import settings
from django.core.management import get_commands
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase

from qc_tool.database.policy import baseline_paths
from qc_tool.database.policy import load_policy
from qc_tool.database.policy import MIGRATION_MODULES


class CentralDatabaseDiscoveryTests(SimpleTestCase):
    def test_migration_identities_resolve_to_the_shared_package(self):
        loader = MigrationLoader(None)
        if load_policy()["phase"] == "draft":
            self.assertFalse(loader.disk_migrations)
            self.assertTrue(all(value is None for value in settings.MIGRATION_MODULES.values()))
        for app, name in load_policy()["baselines"].items():
            with self.subTest(app=app):
                migration = loader.disk_migrations[(app, name)]
                self.assertEqual(migration.app_label, app)
                self.assertEqual(
                    type(migration).__module__,
                    f"{MIGRATION_MODULES[app]}.{name}",
                )
                self.assertTrue(migration.initial)

    def test_command_is_discovered_from_the_database_package(self):
        self.assertEqual(get_commands()["database"], "qc_tool.database")

    def test_every_first_party_model_app_uses_central_migrations(self):
        for config in apps.get_app_configs():
            if config.name.startswith("qc_tool.") and list(config.get_models()):
                with self.subTest(app=config.label):
                    self.assertIn(config.label, MIGRATION_MODULES)
                    self.assertTrue(
                        MIGRATION_MODULES[config.label].startswith("qc_tool.database.migrations.")
                    )

    def test_component_apps_have_no_local_migration_packages(self):
        for app in MIGRATION_MODULES:
            with self.subTest(app=app):
                self.assertFalse((Path(apps.get_app_config(app).path) / "migrations").exists())

    def test_packaged_policy_resolves_independently_of_the_working_directory(self):
        with TemporaryDirectory(prefix="qc-policy-discovery-") as directory:
            with chdir(directory):
                policy = load_policy()
        if policy["phase"] == "draft":
            self.assertEqual(policy["baselines"], {})
        for path in baseline_paths(policy):
            self.assertTrue(path.startswith("src/qc_tool/database/migrations/"))
