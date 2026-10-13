"""Startup validates schema read-only; automatic initialization is local-only."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


class FrontendSchemaStartupTests(SimpleTestCase):
    def run_startup(self, *, environment="production", auto_initialize=None,
                    unready=False, demo_users="no", retired_option=None):
        source = Path(__file__).resolve().parents[5] / "docker" / "run_frontend.sh"
        with TemporaryDirectory(prefix="qc-startup-test-") as temporary:
            root = Path(temporary)
            log = root / "commands.log"
            stub = (
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$QC_STARTUP_TEST_LOG"\n'
                'if [ "$*" = "-m qc_tool.frontend.manage database check" ]; then\n'
                '    exit "$QC_STARTUP_TEST_UNREADY"\n'
                'fi\n'
            )
            for executable in ("python3", "gunicorn"):
                path = root / executable
                path.write_text(stub)
                path.chmod(0o755)
            # Keep the production script's control flow; replace only its
            # image-specific working directory for portable test execution.
            script = source.read_text().replace(
                "cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend",
                'cd "$QC_STARTUP_TEST_DIRECTORY"',
            )
            child_environment = {
                **os.environ,
                "PATH": f"{root}:{os.environ.get('PATH', '')}",
                "QC_STARTUP_TEST_LOG": str(log),
                "QC_STARTUP_TEST_DIRECTORY": str(root),
                "QC_STARTUP_TEST_UNREADY": "1" if unready else "0",
                "QC_TOOL_ENVIRONMENT": environment,
                "QC_TOOL_BOOTSTRAP_DEMO_USERS": demo_users,
                "QC_TOOL_DEV_SERVER": "no",
            }
            # Inherited operator options must not select a fixture's mode.
            child_environment.pop("QC_TOOL_MIGRATE_ON_STARTUP", None)
            child_environment.pop("QC_TOOL_INITIALIZE_ON_STARTUP", None)
            if auto_initialize is not None:
                child_environment["QC_TOOL_INITIALIZE_ON_STARTUP"] = auto_initialize
            if retired_option is not None:
                child_environment["QC_TOOL_MIGRATE_ON_STARTUP"] = retired_option
            result = subprocess.run(
                ["sh"], input=script, text=True, capture_output=True,
                env=child_environment,
            )
            commands = log.read_text().splitlines() if log.exists() else []
        return result, commands

    def test_production_defaults_to_read_only_schema_check(self):
        result, commands = self.run_startup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[0], "-m qc_tool.frontend.manage database check")
        self.assertNotIn("-m qc_tool.frontend.manage database apply", commands)
        self.assertIn("qc_tool.frontend.wsgi:application", commands[-1])

    def test_unready_schema_stops_before_static_collection_or_web_startup(self):
        result, commands = self.run_startup(unready=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, ["-m qc_tool.frontend.manage database check"])
        self.assertIn("Database is not ready", result.stderr)

    def test_production_rejects_automatic_initialization(self):
        result, commands = self.run_startup(auto_initialize="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_local_opt_in_initializes_then_checks_schema(self):
        for environment in ("development", "test"):
            with self.subTest(environment=environment):
                result, commands = self.run_startup(environment=environment, auto_initialize="yes")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(commands[:2], [
                    "-m qc_tool.frontend.manage database apply",
                    "-m qc_tool.frontend.manage database check",
                ])

    def test_unknown_startup_mode_is_rejected(self):
        result, commands = self.run_startup(auto_initialize="perhaps")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_development_demo_accounts_do_not_import_or_assign_products(self):
        result, commands = self.run_startup(
            environment="development", auto_initialize="yes", demo_users="yes",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "-m qc_tool.frontend.manage create_default_user "
            "--username product_manager --password product_manager --group product_manager",
            commands,
        )
        self.assertFalse(any("--product" in command for command in commands))
        self.assertFalse(any("sync_product" in command for command in commands))

    def test_production_rejects_predictable_demo_users(self):
        result, commands = self.run_startup(demo_users="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("create_default_user" in command for command in commands))
        self.assertFalse(any("wsgi:application" in command for command in commands))
        self.assertIn("Refusing to create predictable demo users", result.stderr)

    def test_retired_option_is_rejected_even_when_disabled_or_empty(self):
        for value in ("yes", "no", ""):
            with self.subTest(value=value):
                result, commands = self.run_startup(retired_option=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(commands, [])
                self.assertIn("QC_TOOL_MIGRATE_ON_STARTUP is unsupported", result.stderr)
