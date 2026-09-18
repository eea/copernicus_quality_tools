"""Production startup checks migration readiness without changing the schema."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


class FrontendMigrationStartupTests(SimpleTestCase):
    def run_startup(self, *, environment="production", auto_migrate="no", pending=False, demo_users="no"):
        source = Path(__file__).resolve().parents[5] / "docker" / "run_frontend.sh"
        with TemporaryDirectory(prefix="qc-startup-test-") as temporary:
            root = Path(temporary)
            log = root / "commands.log"
            stub = (
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$QC_STARTUP_TEST_LOG"\n'
                'if [ "$*" = "-m qc_tool.frontend.manage database check" ]; then\n'
                '    exit "$QC_STARTUP_TEST_PENDING"\n'
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
            result = subprocess.run(
                ["sh"], input=script, text=True, capture_output=True,
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ.get('PATH', '')}",
                    "QC_STARTUP_TEST_LOG": str(log),
                    "QC_STARTUP_TEST_DIRECTORY": str(root),
                    "QC_STARTUP_TEST_PENDING": "1" if pending else "0",
                    "QC_TOOL_ENVIRONMENT": environment,
                    "QC_TOOL_MIGRATE_ON_STARTUP": auto_migrate,
                    "QC_TOOL_BOOTSTRAP_DEMO_USERS": demo_users,
                    "QC_TOOL_DEV_SERVER": "no",
                },
            )
            commands = log.read_text().splitlines() if log.exists() else []
        return result, commands

    def test_production_only_checks_migrations_before_starting(self):
        result, commands = self.run_startup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[0], "-m qc_tool.frontend.manage database check")
        self.assertNotIn("-m qc_tool.frontend.manage database apply", commands)
        self.assertIn("qc_tool.frontend.wsgi:application", commands[-1])

    def test_pending_migrations_stop_before_static_collection_or_web_startup(self):
        result, commands = self.run_startup(pending=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, ["-m qc_tool.frontend.manage database check"])
        self.assertIn("committed migrations", result.stderr)

    def test_production_rejects_automatic_migrations(self):
        result, commands = self.run_startup(auto_migrate="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_development_opt_in_applies_then_checks_migrations(self):
        result, commands = self.run_startup(environment="development", auto_migrate="yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[:2], [
            "-m qc_tool.frontend.manage database apply",
            "-m qc_tool.frontend.manage database check",
        ])

    def test_unknown_startup_mode_is_rejected(self):
        result, commands = self.run_startup(auto_migrate="perhaps")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])

    def test_development_demo_accounts_do_not_import_or_assign_products(self):
        result, commands = self.run_startup(
            environment="development", auto_migrate="yes", demo_users="yes",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "-m qc_tool.frontend.manage create_default_user "
            "--username product_manager --password product_manager --group product_manager",
            commands,
        )
        self.assertFalse(any("--product" in command for command in commands))
        self.assertFalse(any("sync_product" in command for command in commands))
