"""Whole-application migration guards and PostgreSQL deployment serialization."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db import models
from django.db.migrations.state import ProjectState
from django.db.migrations.recorder import MigrationRecorder
from django.apps import apps
from django.test import SimpleTestCase
from django.test import TransactionTestCase
from django.test import override_settings

from qc_tool.database.deployment import MIGRATION_LOCK
from qc_tool.database.deployment import migration_lock
from qc_tool.database.deployment import check_draft_tables
from qc_tool.database.policy import load_policy


class DatabaseReleaseGuardTests(SimpleTestCase):
    @override_settings(IS_SECURE_ENVIRONMENT=True)
    def test_draft_cannot_be_used_by_production(self):
        with patch(
            "qc_tool.database.deployment.release_policy",
            return_value={"phase": "draft", "baselines": {}},
        ):
            for action in ("plan", "check", "apply"):
                with self.subTest(action=action):
                    with self.assertRaisesMessage(CommandError, "draft schema"):
                        call_command("database", action, skip_checks=True)

    def test_timeouts_must_be_positive_and_bounded(self):
        for value in (0, -1, 2147483648):
            with self.subTest(value=value):
                with self.assertRaises(CommandError):
                    call_command("database", "apply", lock_timeout_ms=value, skip_checks=True)


@override_settings(IS_SECURE_ENVIRONMENT=False)
class DatabaseDeploymentTests(TransactionTestCase):
    def test_draft_schema_has_no_applied_migration_history_or_products(self):
        if load_policy()["phase"] != "draft":
            self.skipTest("Released schemas have committed history.")
        self.assertFalse(MigrationRecorder(connection).applied_migrations())
        self.assertFalse(apps.get_model("dashboard", "Product").objects.exists())

    def test_draft_check_detects_model_field_missing_from_existing_schema(self):
        state = ProjectState.from_apps(apps)
        state.add_field(
            "dashboard", "product", "draft_probe",
            models.CharField(max_length=20, null=True), preserve_default=True,
        )
        with patch("qc_tool.database.deployment.apps", state.apps):
            with self.assertRaisesMessage(CommandError, "columns differ in dashboard_product"):
                check_draft_tables(connection)
        # The readiness check must not add the proposed field or reset data.
        check_draft_tables(connection)

    def test_whole_application_readiness_and_repeated_application(self):
        output = StringIO()
        call_command("database", "plan", stdout=output)
        call_command("database", "check", stdout=output)
        call_command("database", "apply", stdout=output)
        call_command("database", "check", stdout=output)

    def test_postgres_lock_excludes_other_migrators_and_restores_timeouts(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory locks are backend-specific.")
        other = connection.copy(alias="migration_lock_test")
        self.addCleanup(other.close)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
            previous = cursor.fetchone()
        with migration_lock(connection, lock_timeout_ms=1000, statement_timeout_ms=3000):
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
                self.assertEqual(cursor.fetchone(), ("1s", "3s"))
            with self.assertRaisesMessage(CommandError, "Another QC Tool"):
                with migration_lock(other, lock_timeout_ms=1000, statement_timeout_ms=3000):
                    self.fail("A second migration job acquired the same lock.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
            self.assertEqual(cursor.fetchone(), previous)
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", MIGRATION_LOCK)
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", MIGRATION_LOCK)

    def test_postgres_lock_releases_after_failure(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory locks are backend-specific.")
        with self.assertRaisesRegex(RuntimeError, "probe"):
            with migration_lock(connection, lock_timeout_ms=1000, statement_timeout_ms=3000):
                raise RuntimeError("probe")
        other = connection.copy(alias="migration_failure_test")
        self.addCleanup(other.close)
        with migration_lock(other, lock_timeout_ms=1000, statement_timeout_ms=3000):
            pass

    def test_closed_postgres_connection_does_not_mask_the_migration_error(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory locks are backend-specific.")
        with self.assertRaisesRegex(RuntimeError, "original migration failure"):
            with migration_lock(connection, lock_timeout_ms=1000, statement_timeout_ms=3000):
                connection.close()
                raise RuntimeError("original migration failure")
        other = connection.copy(alias="migration_closed_connection_test")
        self.addCleanup(other.close)
        with migration_lock(other, lock_timeout_ms=1000, statement_timeout_ms=3000):
            pass
