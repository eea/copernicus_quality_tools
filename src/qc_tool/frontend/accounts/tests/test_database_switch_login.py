"""Maintenance credentials retain an explicit, live-checked database origin."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, authenticate
from django.contrib.sessions.backends.db import SessionStore
from django.conf import settings
from django.db import OperationalError, connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.frontend.accounts.authentication.backends import MaintenanceBackend
from qc_tool.frontend.accounts.authentication.maintenance import (
    BACKEND, MARKER, ORIGIN_DATABASE, authentication_scope, login_without_database_writes,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.users import provision_user
from qc_tool.frontend.dashboard.middleware import MaintenanceSessionMiddleware


@override_settings(AUTHENTICATION_BACKENDS=(BACKEND,))
class DatabaseSwitchLoginTests(TestCase):
    password = "switch-operator-password"

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=Path(directory) / "maintenance"))
        self.administrator = provision_user(username="switch-administrator", password=self.password,
                                           groups=(Role.ADMIN.value,)).user
        self.manager = provision_user(username="switch-manager", password=self.password,
                                     groups=(Role.PRODUCT_MANAGER.value,)).user
        self.request = RequestFactory().post("/accounts/login/")
        self.request.maintenance_active = True
        self.request.maintenance_status = {"enabled": True, "generation": 7}
        self.request.session = SessionStore()

    def test_normal_session_promotion_binds_database_and_maintenance_backend_without_sql(self):
        self.administrator.backend = "some.normal.Backend"
        with patch("qc_tool.database.selection.current_database", return_value="origin_database"), CaptureQueriesContext(connection) as queries:
            login_without_database_writes(self.request, self.administrator)
        self.assertEqual(self.request.session[ORIGIN_DATABASE], "origin_database")
        self.assertEqual(self.request.session[BACKEND_SESSION_KEY], BACKEND)
        self.assertEqual(self.request.session[HASH_SESSION_KEY], self.administrator.get_session_auth_hash())
        self.assertEqual(self.request.session[SESSION_KEY], str(self.administrator.pk))
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")) for query in queries))

    def test_unavailable_old_sql_session_becomes_anonymous_without_blocking_login(self):
        self.request.COOKIES[settings.SESSION_COOKIE_NAME] = "old-normal-sql-session-cookie"

        def view(request):
            self.assertIsNone(request.session.get(SESSION_KEY))
            self.assertTrue(request.session.get(MARKER))
            return HttpResponse("maintenance login remains available")

        with patch.object(SessionStore, "load", side_effect=OperationalError("selected database unavailable")):
            response = MaintenanceSessionMiddleware(view)(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.request._maintenance_cookie_session)

    def test_origin_administrator_is_loaded_from_pinned_alias_after_switch(self):
        with (authentication_scope("origin_database"),
              patch("qc_tool.database.selection.current_database", return_value="restored_database"),
              patch("qc_tool.database.selection.alias_for_database", return_value="default") as alias):
            loaded = MaintenanceBackend().get_user(self.administrator.pk)
        self.assertEqual(loaded.pk, self.administrator.pk)
        alias.assert_called_once_with("origin_database")

    def test_origin_manager_is_refused_after_switch_and_revoked_admin_is_refused(self):
        with (authentication_scope("origin_database"),
              patch("qc_tool.database.selection.current_database", return_value="restored_database"),
              patch("qc_tool.database.selection.alias_for_database", return_value="default")):
            self.assertIsNone(MaintenanceBackend().get_user(self.manager.pk))
            self.administrator.groups.clear()
            self.assertIsNone(MaintenanceBackend().get_user(self.administrator.pk))

    def test_unreachable_destination_allows_only_origin_admin_in_same_window(self):
        def alias(name):
            if name == "restored_database":
                raise OperationalError("isolated unreachable destination")
            return "default"

        state = {"active": "restored_database", "previous": "origin_database",
                 "configured": {"name": "origin_database"}, "maintenance_generation": 7}
        with (patch("qc_tool.database.selection.current_database", return_value="restored_database"),
              patch("qc_tool.database.selection.read_state", return_value=state),
              patch("qc_tool.database.selection.alias_for_database", side_effect=alias)):
            operator = authenticate(self.request, username=self.administrator.username, password=self.password)
            self.assertEqual(operator.pk, self.administrator.pk)
            self.assertIsNone(authenticate(self.request, username=self.manager.username, password=self.password))
            state["maintenance_generation"] = 6
            self.assertIsNone(authenticate(self.request, username=self.administrator.username, password=self.password))

    def test_later_switch_never_reuses_an_administrator_from_older_primary(self):
        # A previously retained primary can still contain an administrator
        # revoked from the more recent B -> C deployment. It is not B's rescue.
        state = {"active": "database_c", "previous": "database_b",
                 "configured": {"name": "old_primary_a"}, "maintenance_generation": 7}

        def alias(name):
            if name == "old_primary_a":
                return "default"  # This fixture really has a usable admin.
            raise OperationalError("administrator unavailable in current window")

        with (patch("qc_tool.database.selection.current_database", return_value="database_c"),
              patch("qc_tool.database.selection.read_state", return_value=state),
              patch("qc_tool.database.selection.alias_for_database", side_effect=alias) as aliases):
            self.assertIsNone(authenticate(self.request, username=self.administrator.username, password=self.password))
        self.assertEqual([call.args[0] for call in aliases.call_args_list], ["database_c", "database_b"])
