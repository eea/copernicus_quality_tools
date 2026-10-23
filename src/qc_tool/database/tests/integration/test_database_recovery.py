"""Startup can admit a read-only rescue UI without adopting a broken target."""

from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.database import selection
from qc_tool.database.transfers import store
from qc_tool.frontend.dashboard.services import maintenance


class DatabaseRecoveryOptionTests(SimpleTestCase):
    def test_recovery_flag_is_restricted_to_default_read_only_check(self):
        for action, alias in (("apply", "default"), ("plan", "default"), ("check", "other")):
            with self.subTest(action=action, alias=alias), patch(
                "qc_tool.database.management.commands.database.manage_database",
            ) as operation:
                with self.assertRaisesMessage(CommandError, "supported only"):
                    call_command("database", action, database=alias, allow_maintenance_recovery=True)
                operation.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "PostgreSQL maintenance recovery")
@override_settings(MAINTENANCE_MODE=False)
class PostgreSQLDatabaseRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.source = connection.settings_dict["NAME"]
        self.assertTrue(self.source.startswith("test_"))
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_CONFIGURED_DATABASE=deepcopy(connection.settings_dict),
            QC_TOOL_TRANSFER_DIR=root / "transfers", QC_TOOL_MAINTENANCE_DIR=root / "maintenance",
        ))
        self.administrator = get_user_model().objects.create_superuser("startup-rescue", "", "rescue-password")
        with connection.cursor() as cursor:
            cursor.execute("SELECT oid FROM pg_database WHERE datname=current_database()")
            self.source_oid = cursor.fetchone()[0]
        self.generation = maintenance.enable(self.administrator, 0)["generation"]
        maintenance.advance(self.generation)
        self.alias = selection.alias_for_database(self.source)
        self.allowed = type(self).databases
        type(self).databases = self.allowed | {self.alias}
        self.failed_target = "qc_unavailable_" + uuid4().hex

    def tearDown(self):
        (store._directory_path() / "database-selection.json").unlink(missing_ok=True)
        connection.close()
        connections[self.alias].close()
        del connections[self.alias]
        connections.databases.pop(self.alias, None)
        type(self).databases = self.allowed

    def selected(self, **overrides):
        state = selection.read_state()
        state.update(active=self.failed_target, previous=self.source, revision=1,
                     changed_at=store.now(), maintenance_generation=self.generation,
                     operation_id=str(uuid4()), activation={
                         "source_native": {"oid": self.source_oid, "review_hash": "a" * 64},
                         "source_files": {"fingerprint": "b" * 64},
                     })
        state.update(overrides)
        selection.write_state(state, 0)
        return state

    def check(self, **options):
        output = StringIO()
        call_command("database", "check", stdout=output, stderr=StringIO(), **options)
        return output.getvalue().strip()

    def test_matching_schema_has_exact_machine_mode_without_recovery(self):
        self.assertEqual(self.check(allow_maintenance_recovery=True), "ready")

    def test_unavailable_selected_database_admits_only_read_only_recovery(self):
        state = self.selected()
        status = maintenance.read_status()
        with CaptureQueriesContext(connections[self.alias]) as queries:
            self.assertEqual(self.check(allow_maintenance_recovery=True), "maintenance-recovery")
        self.assertEqual(selection.read_state(), state)
        self.assertEqual(maintenance.read_status(), status)
        self.assertEqual([
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))
        ], [])
        with self.assertRaises(CommandError):
            self.check()

    def test_recovery_refuses_wrong_generation_or_missing_source_proof(self):
        for changes in ({"maintenance_generation": self.generation + 1}, {"activation": {}}):
            with self.subTest(changes=changes):
                self.selected(**changes)
                with self.assertRaises(CommandError) as error:
                    self.check(allow_maintenance_recovery=True)
                self.assertEqual(error.exception.returncode, 2)
                (store._directory_path() / "database-selection.json").unlink()

    def test_recovery_requires_retained_database_identity_and_usable_administrator(self):
        self.administrator.set_unusable_password()
        self.administrator.save(update_fields=("password",))
        self.selected()
        with self.assertRaisesMessage(CommandError, "usable active QC Tool administrator") as error:
            self.check(allow_maintenance_recovery=True)
        self.assertEqual(error.exception.returncode, 2)

    def test_recovery_refuses_when_maintenance_has_ended(self):
        self.selected()
        maintenance.disable(self.administrator, self.generation)
        with self.assertRaises(CommandError) as error:
            self.check(allow_maintenance_recovery=True)
        self.assertEqual(error.exception.returncode, 2)
