"""A database selection typo must never select a different persistent store."""

import os
import subprocess
import sys

from django.test import SimpleTestCase


class DatabaseSettingsTests(SimpleTestCase):
    def settings_process(self, engine):
        environment = {
            **os.environ,
            "QC_TOOL_ENVIRONMENT": "test",
            "DB_ENGINE": engine,
        }
        return subprocess.run(
            [sys.executable, "-c",
             "from qc_tool.frontend.settings import DATABASES; "
             "print(DATABASES['default']['ENGINE'])"],
            env=environment, capture_output=True, text=True, timeout=15,
        )

    def test_unknown_database_engine_refuses_startup(self):
        for engine in ("postgresql", "postgress", "", "mysql"):
            with self.subTest(engine=engine):
                result = self.settings_process(engine)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DB_ENGINE must be sqlite or postgres", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_supported_database_engines_select_the_expected_backend(self):
        for engine, backend in (("postgres", "qc_tool.database.backends.postgresql"),
                                ("sqlite", "django.db.backends.sqlite3")):
            with self.subTest(engine=engine):
                result = self.settings_process(engine)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), backend)
