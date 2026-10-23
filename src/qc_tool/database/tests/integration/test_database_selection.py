"""Selection journals, request scopes and PostgreSQL connection boundaries."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.http import StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TransactionTestCase, override_settings

from qc_tool.database import selection
from qc_tool.database.middleware import DatabaseScopeMiddleware
from qc_tool.database.transfers import store


CONFIG = {
    "ENGINE": "qc_tool.database.backends.postgresql", "NAME": "primary_database",
    "HOST": "database.internal", "PORT": "5432", "USER": "application",
}


@override_settings(QC_TOOL_CONFIGURED_DATABASE=CONFIG)
class DatabaseSelectionTests(SimpleTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory())) / "transfers"
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=self.directory))
        self.enterContext(patch.object(selection, "connections", {
            "default": SimpleNamespace(settings_dict=deepcopy(CONFIG)),
        }))

    def change(self, name="restored_database"):
        state = selection.read_state()
        revision = state["revision"]
        state.update(active=name, previous=state["active"], revision=revision + 1,
                     changed_at="2026-10-21T12:00:00+00:00", operation_id=str(uuid4()),
                     maintenance_generation=5, activation={"access_proof": {"username": "operator"}})
        return selection.write_state(state, revision)

    def test_missing_pointer_selects_primary_without_creating_storage(self):
        self.assertEqual(selection.current_database(), CONFIG["NAME"])
        self.assertEqual(selection.read_state()["revision"], 0)
        self.assertFalse(self.directory.exists())

    def test_private_pointer_retains_binding_metadata_and_checks_revision(self):
        state = self.change()
        self.assertEqual(selection.current_database(), "restored_database")
        self.assertEqual(selection.read_state(), state)
        self.assertEqual((self.directory / "database-selection.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(selection.DatabaseSelectionError):
            selection.write_state(state, 0)
        state.update(configured={**state["configured"], "host": "another-server"}, revision=2)
        with self.assertRaises(selection.DatabaseSelectionError):
            selection.write_state(state, 1)

    def test_corrupt_or_foreign_pointer_fails_closed(self):
        self.change()
        path = self.directory / "database-selection.json"
        for value in ({"active": "other_database"}, {**selection.read_state(), "configured": {}}):
            store.write_json(path, value)
            with self.assertRaises(selection.DatabaseSelectionError):
                selection.current_database()
        path.write_text("not json")
        with self.assertRaises(selection.DatabaseSelectionError):
            selection.current_database()

    def test_test_runner_database_override_cannot_follow_live_pointer(self):
        selection.connections["default"].settings_dict["NAME"] = "test_disposable_database"
        with patch.object(selection, "read_state", side_effect=AssertionError("live pointer read")):
            self.assertEqual(selection.current_database(), "test_disposable_database")

    def test_request_stream_and_close_keep_original_database_after_switch(self):
        observed = []

        def view(request):
            observed.append(("view", selection.current_database()))
            self.change()

            def content():
                observed.append(("stream", selection.current_database()))
                yield b"data"

            response = StreamingHttpResponse(content())
            response._resource_closers.append(lambda: observed.append(("close", selection.current_database())))
            return response

        response = DatabaseScopeMiddleware(view)(RequestFactory().get("/admin/"))
        self.assertEqual(selection.current_database(), "restored_database")
        self.assertEqual(b"".join(response.streaming_content), b"data")
        response.close()
        self.assertEqual(observed, [("view", CONFIG["NAME"]), ("stream", CONFIG["NAME"]), ("close", CONFIG["NAME"])])

    def test_broken_pointer_blocks_requests_but_keeps_liveness(self):
        self.change()
        (self.directory / "database-selection.json").write_text("broken")
        handler = Mock(return_value=StreamingHttpResponse([b"healthy"]))
        middleware = DatabaseScopeMiddleware(handler)
        self.assertEqual(middleware(RequestFactory().get("/admin/")).status_code, 503)
        handler.assert_not_called()
        self.assertEqual(middleware(RequestFactory().get("/health")).status_code, 200)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL connection selection")
class PostgreSQLSelectionTests(TransactionTestCase):
    def test_origin_alias_enforces_read_only_on_incidental_model_save(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        user = get_user_model().objects.create_user(username="read-only-origin")
        with override_settings(QC_TOOL_CONFIGURED_DATABASE=deepcopy(connection.settings_dict)):
            alias = selection.alias_for_database(connection.settings_dict["NAME"])
            allowed = type(self).databases
            type(self).databases = allowed | {alias}
            try:
                retained_user = get_user_model().objects.using(alias).get(pk=user.pk)
                retained_user.first_name = "must-not-be-written"
                with self.assertRaises(DatabaseError):
                    retained_user.save(using=alias)
                user.refresh_from_db()
                self.assertEqual(user.first_name, "")
            finally:
                connections[alias].close()
                del connections[alias]
                connections.databases.pop(alias, None)
                type(self).databases = allowed

    def test_cursor_switches_after_transaction_and_test_database_stays_isolated(self):
        # This test may only provision/drop its own generated disposable target.
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        source = connection.settings_dict["NAME"]
        target = "qc_selection_" + uuid4().hex
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {quote(target)} TEMPLATE template0")
        directory = self.enterContext(TemporaryDirectory())
        try:
            with override_settings(QC_TOOL_TRANSFER_DIR=Path(directory) / "transfers",
                                   QC_TOOL_CONFIGURED_DATABASE=deepcopy(connection.settings_dict)):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT current_database()")
                        self.assertEqual(cursor.fetchone()[0], source)
                    state = selection.read_state()
                    state.update(active=target, previous=source, revision=1, changed_at="2026-10-21T12:00:00+00:00")
                    selection.write_state(state, 0)
                    self.assertEqual(connection.get_connection_params()["dbname"], source)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT current_database()")
                        self.assertEqual(cursor.fetchone()[0], source)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    self.assertEqual(cursor.fetchone()[0], target)

                def background_database():
                    local = connections["default"]
                    try:
                        with local.cursor() as cursor:
                            cursor.execute("SELECT current_database()")
                            return cursor.fetchone()[0]
                    finally:
                        local.close()

                with ThreadPoolExecutor(max_workers=1) as executor:
                    self.assertEqual(executor.submit(background_database).result(timeout=15), target)
                restarted = subprocess.run([
                    sys.executable, "-c",
                    "import django; django.setup(); from django.db import connection; "
                    "cursor=connection.cursor(); cursor.execute('SELECT current_database()'); "
                    "print(cursor.fetchone()[0]); connection.close()",
                ], env={**os.environ, "POSTGRES_DB": source,
                        "QC_TOOL_TRANSFER_DIR": str(Path(directory) / "transfers")},
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(restarted.returncode, 0, restarted.stderr)
                self.assertEqual(restarted.stdout.strip(), target)
                state.update(active=source, previous=target, revision=2)
                selection.write_state(state, 1)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    self.assertEqual(cursor.fetchone()[0], source)
        finally:
            connection.close()
            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE {quote(target)} WITH (FORCE)")
