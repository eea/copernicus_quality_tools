"""Startup can admit a read-only rescue UI without adopting a broken target."""

from copy import deepcopy
from io import StringIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test import RequestFactory
from django.http import HttpResponse
from django.urls import reverse
from django.test.utils import CaptureQueriesContext

from qc_tool.database import selection
from qc_tool.database.policy import MANAGED_APPS
from qc_tool.database.tests.integration.test_deployment import fresh_sqlite
from qc_tool.database.transfers import store
from qc_tool.common import CONFIG
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
        # End a healthy maintenance window first, then model an unavailable
        # selected copy. The central guard now correctly refuses reopening an
        # already unavailable target, so that cannot establish this fixture.
        maintenance.disable(self.administrator, self.generation)
        self.selected()
        with self.assertRaises(CommandError) as error:
            self.check(allow_maintenance_recovery=True)
        self.assertEqual(error.exception.returncode, 2)


@override_settings(MAINTENANCE_MODE=False)
class ModelsOnlyUpgradeStartupTests(SimpleTestCase):
    databases = {"default"}

    def test_legacy_upgrade_retains_worker_control_and_requires_fresh_positive_acknowledgment(self):
        received = []

        class WorkerProtocol(BaseHTTPRequestHandler):
            def do_PUT(self):
                command = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers.get("Authorization"), command))
                raw = json.dumps({**command, "quiescent": self.server.quiescent}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), WorkerProtocol)
        server.quiescent = False
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with fresh_sqlite() as probe, TemporaryDirectory(prefix="qc-upgrade-workers-") as temporary:
                root = Path(temporary)
                with override_settings(QC_TOOL_CONFIGURED_DATABASE=deepcopy(probe.settings_dict),
                                       QC_TOOL_TRANSFER_DIR=root / "transfers", QC_TOOL_MAINTENANCE_DIR=root / "maintenance"), \
                        patch.dict(CONFIG, worker_port=server.server_address[1]), \
                        patch("qc_tool.frontend.dashboard.services.maintenance.workers.get_worker_token", return_value="migration-worker-review"):
                    with override_settings(MIGRATION_MODULES=dict.fromkeys(MANAGED_APPS)):
                        call_command("migrate", run_syncdb=True, interactive=False, stdout=StringIO())
                    administrator = get_user_model().objects.create_superuser("worker-upgrade-admin", "", "upgrade-password")
                    maintenance.register_worker("http://127.0.0.1:%s/" % server.server_address[1])
                    generation = maintenance.enable(administrator, 0)["generation"]
                    self.assertEqual(maintenance.advance(generation)["phase"], "stopping")
                    with self.assertRaises(CommandError):
                        call_command("database", "check", allow_maintenance_recovery=True, stdout=StringIO(), stderr=StringIO())
                    server.quiescent = True
                    self.assertEqual(maintenance.advance(generation)["phase"], "ready")
                    output = StringIO()
                    call_command("database", "check", allow_maintenance_recovery=True, stdout=output, stderr=StringIO())
                    self.assertEqual(output.getvalue().strip(), "maintenance-recovery")
                    from qc_tool.frontend.dashboard.middleware import MaintenanceModeMiddleware
                    from qc_tool.frontend.dashboard.views.workers import worker_maintenance
                    handler = MaintenanceModeMiddleware(worker_maintenance)
                    before = maintenance.read_status()
                    with CaptureQueriesContext(probe) as queries:
                        response = handler(RequestFactory().get(reverse("worker_maintenance"), REMOTE_ADDR="127.0.0.1"))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(json.loads(response.content), {"enabled": True, "generation": generation})
                    self.assertEqual(list(queries), [])
                    self.assertEqual(maintenance.read_status(), before)
                    self.assertEqual(received[-1][1], "WorkerToken migration-worker-review")
                    self.assertEqual(received[-1][2], {"enabled": True, "generation": generation})
                    # A restarted or busy worker revokes prior readiness; a
                    # timeout or previously accepted acknowledgment is no bypass.
                    server.quiescent = False
                    self.assertEqual(maintenance.advance(generation)["phase"], "stopping")
                    self.assertNotIn("django_migrations", probe.introspection.table_names())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_supported_predecessor_starts_only_admin_recovery_in_ready_maintenance(self):
        with fresh_sqlite() as probe, TemporaryDirectory(prefix="qc-upgrade-startup-") as temporary:
            root = Path(temporary)
            with override_settings(QC_TOOL_CONFIGURED_DATABASE=deepcopy(probe.settings_dict),
                                   QC_TOOL_TRANSFER_DIR=root / "transfers", QC_TOOL_MAINTENANCE_DIR=root / "maintenance"):
                with override_settings(MIGRATION_MODULES=dict.fromkeys(MANAGED_APPS)):
                    call_command("migrate", run_syncdb=True, interactive=False, stdout=StringIO())
                administrator = get_user_model().objects.create_superuser("upgrade-administrator", "", "upgrade-password")
                self.assertNotIn("django_migrations", probe.introspection.table_names())
                with self.assertRaises(CommandError):
                    call_command("database", "check", allow_maintenance_recovery=True, stdout=StringIO(), stderr=StringIO())
                generation = maintenance.enable(administrator, 0)["generation"]
                with self.assertRaises(CommandError):
                    call_command("database", "check", allow_maintenance_recovery=True, stdout=StringIO(), stderr=StringIO())
                self.assertEqual(maintenance.advance(generation)["phase"], "ready")
                output = StringIO()
                before = maintenance.read_status()
                with CaptureQueriesContext(probe) as queries:
                    call_command("database", "check", allow_maintenance_recovery=True, stdout=output, stderr=StringIO())
                self.assertEqual(output.getvalue().strip(), "maintenance-recovery")
                self.assertEqual(maintenance.read_status(), before)
                self.assertNotIn("django_migrations", probe.introspection.table_names())
                self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP ")) for query in queries))
                from qc_tool.frontend.dashboard.middleware import MaintenanceModeMiddleware
                handler = MaintenanceModeMiddleware(lambda request: HttpResponse("administrator recovery"))
                requests = RequestFactory()
                workspace = handler(requests.get(reverse("dashboard_home")))
                self.assertEqual(workspace.status_code, 503)
                self.assertIn(reverse("admin_migrations").encode(), workspace.content)
                self.assertEqual(handler(requests.get(reverse("admin_migrations"))).status_code, 200)
                self.assertEqual(handler(requests.get("/health")).status_code, 200)
                with self.assertRaises(CommandError):
                    call_command("database", "check", stdout=StringIO())
                administrator.set_unusable_password()
                administrator.save(update_fields=("password",))
                with self.assertRaises(CommandError):
                    call_command("database", "check", allow_maintenance_recovery=True, stdout=StringIO(), stderr=StringIO())
