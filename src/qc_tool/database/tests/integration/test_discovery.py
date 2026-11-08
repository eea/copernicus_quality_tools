"""Django discovers current models and the native migration database command."""

from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from django.apps import apps
from django.conf import settings
from django.core.management import get_commands
from django.test import SimpleTestCase

from qc_tool.database.checks.source import check_source
from qc_tool.database.policy import load_policy, migration_modules, MANAGED_APPS


class CentralDatabaseDiscoveryTests(SimpleTestCase):
    def test_all_supported_apps_use_native_django_history(self):
        expected = {}
        self.assertEqual(migration_modules(), expected)
        self.assertEqual(settings.MIGRATION_MODULES, expected)
        for label in MANAGED_APPS:
            with self.subTest(app=label):
                self.assertIsNotNone(apps.get_app_config(label))

    def test_command_is_discovered_without_a_legacy_converter(self):
        commands = get_commands()
        self.assertEqual(commands["database"], "qc_tool.database")
        self.assertNotIn("import_legacy_dump", commands)

    def test_every_managed_first_party_model_has_native_history(self):
        for model in apps.get_models(include_auto_created=True):
            config = model._meta.app_config
            if model._meta.managed and config.name.startswith("qc_tool."):
                with self.subTest(model=model._meta.label):
                    self.assertIn(config.label, MANAGED_APPS)
                    self.assertNotIn(config.label, settings.MIGRATION_MODULES)

    def test_first_party_apps_have_owned_migration_packages(self):
        check_source()
        for config in apps.get_app_configs():
            if config.name.startswith("qc_tool."):
                with self.subTest(app=config.label):
                    self.assertTrue((Path(config.path) / "migrations" / "0001_initial.py").is_file())

    def test_packaged_policy_resolves_independently_of_the_working_directory(self):
        with TemporaryDirectory(prefix="qc-policy-discovery-") as directory:
            with chdir(directory):
                self.assertEqual(load_policy()["phase"], "managed")
                self.assertEqual(load_policy()["release"], "3.0.0")
