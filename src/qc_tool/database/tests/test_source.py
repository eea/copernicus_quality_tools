"""Offline checks for the supported v3 source layout."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qc_tool.database.checks.source import check_source
from qc_tool.database.policy import DatabasePolicyError, parse_policy


class ModelsOnlySourceTests(unittest.TestCase):
    def test_current_application_source(self):
        check_source()

    def test_component_migration_package_is_rejected(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "frontend/dashboard/migrations").mkdir(parents=True)
            with self.assertRaises(DatabasePolicyError):
                check_source(directory)

    def test_local_private_archive_is_not_application_source(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "database/backups/source/database/migrations").mkdir(parents=True)
            check_source(directory)

    def test_legacy_conversion_command_is_rejected(self):
        with TemporaryDirectory() as directory:
            command = Path(directory) / "database/management/commands/import_legacy_dump.py"
            command.parent.mkdir(parents=True)
            command.touch()
            with self.assertRaises(DatabasePolicyError):
                check_source(directory)

    def test_only_models_only_configuration_is_supported(self):
        for document in (
            '{"phase": "released", "baselines": {}}',
            '{"phase": "draft", "baselines": {"accounts": "0001_initial"}}',
            '{"phase": "draft", "baselines": [], "extra": true}',
            '{"phase": "draft", "phase": "draft", "baselines": {}}',
            'invalid JSON',
        ):
            with self.subTest(document=document), self.assertRaises(DatabasePolicyError):
                parse_policy(document)
