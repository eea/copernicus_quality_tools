"""Operator sign-in keeps maintenance SQL quiescent and browser controls safe."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY, authenticate, get_user_model
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.contrib.auth.signals import user_logged_in
from django.contrib.sessions.models import Session
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.maintenance import GENERATION, cookie_session
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.users import provision_user
from qc_tool.frontend.dashboard.services import maintenance


@override_settings(
    MAINTENANCE_MODE=False,
    SESSION_ENGINE="django.contrib.sessions.backends.db",
    PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",
                      "django.contrib.auth.hashers.PBKDF2PasswordHasher"),
    AUTHENTICATION_BACKENDS=(
        "qc_tool.frontend.accounts.authentication.backends.MaintenanceBackend",
        "qc_tool.frontend.accounts.authentication.backends.CaseInsensitiveBackend",
    ),
)
class MaintenanceOperatorLoginTests(TestCase):
    password = "maintenance-operator-password"

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=Path(directory) / "maintenance"))
        self.administrator = provision_user(username="maintenance-administrator", password=self.password,
                                           groups=(Role.ADMIN.value,)).user
        self.manager = provision_user(username="maintenance-manager", password=self.password,
                                     groups=(Role.PRODUCT_MANAGER.value,)).user
        self.superuser = provision_user(username="maintenance-superuser", password=self.password,
                                       is_superuser=True).user
        self.viewer = provision_user(username="maintenance-viewer", password=self.password).user
        self.staff = provision_user(username="maintenance-staff", password=self.password).user
        get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=True)
        self.inactive = provision_user(username="maintenance-inactive", password=self.password,
                                       groups=(Role.ADMIN.value,)).user
        get_user_model().objects.filter(pk=self.inactive.pk).update(is_active=False)
        self.generation = maintenance.enable("isolated test", 0)["generation"]

    def without_writes(self, callback):
        with CaptureQueriesContext(connection) as captured:
            response = callback()
        mutations = [query["sql"] for query in captured if re.match(
            r"\s*(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|REPLACE)\b", query["sql"], re.I,
        )]
        self.assertEqual(mutations, [])
        return response

    def login(self, user, *, endpoint="login", password=None, next_url="", client=None, read_only=True):
        client = client or Client(enforce_csrf_checks=True)
        url = reverse(endpoint)
        run = self.without_writes if read_only else lambda callback: callback()
        page = run(lambda: client.get(url))
        self.assertEqual(page.status_code, 200)
        token = page.context["csrf_token"]
        response = run(lambda: client.post(url, {
            "username": user.username, "password": password or self.password, "next": next_url,
        }, HTTP_X_CSRFTOKEN=str(token)))
        return client, response

    def assert_cookie_identity(self, client, user):
        session = cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value)
        self.assertIsNotNone(session)
        self.assertEqual(session[SESSION_KEY], str(user.pk))
        return session

    def test_both_login_routes_admit_only_live_operator_roles_in_stopping_and_ready(self):
        self.assertEqual(reverse("admin:login"), reverse("admin_login"))
        for phase in ("stopping", "ready"):
            if phase == "ready":
                maintenance.advance(self.generation)
            for endpoint in ("login", "admin:login"):
                for user in (self.administrator, self.manager, self.superuser):
                    with self.subTest(phase=phase, endpoint=endpoint, user=user.username):
                        client, response = self.login(user, endpoint=endpoint, next_url=reverse("products"))
                        destination = reverse("products") if endpoint == "login" else reverse("admin:index")
                        self.assertRedirects(response, destination, fetch_redirect_response=False)
                        self.assert_cookie_identity(client, user)
                        page = self.without_writes(lambda: client.get(reverse("products")))
                        self.assertEqual(page.status_code, 200)
                        self.assertEqual(page["X-QC-Maintenance"], "on")
        self.assertFalse(Session.objects.exists())

    def test_login_forms_remain_interactive_and_csrf_is_required(self):
        for endpoint in ("login", "admin:login"):
            with self.subTest(endpoint=endpoint):
                client = Client(enforce_csrf_checks=True)
                page = self.without_writes(lambda: client.get(reverse(endpoint)))
                self.assertContains(page, "only administrators and product managers can sign in")
                self.assertContains(page, "data-maintenance-exempt")
                self.assertNotContains(page, 'class="qc-maintenance-fields" disabled')
                response = self.without_writes(lambda: client.post(reverse(endpoint), {
                    "username": self.administrator.username, "password": self.password,
                }))
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(SESSION_KEY, cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value))

    def test_default_staff_without_role_inactive_and_wrong_password_are_denied(self):
        for endpoint in ("login", "admin:login"):
            for user, password in ((self.viewer, self.password), (self.staff, self.password),
                                   (self.inactive, self.password), (self.manager, "incorrect")):
                with self.subTest(endpoint=endpoint, user=user.username, password_valid=password == self.password):
                    client, response = self.login(user, endpoint=endpoint, password=password)
                    self.assertEqual(response.status_code, 200)
                    session = cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value)
                    self.assertNotIn(SESSION_KEY, session)
        self.assertFalse(Session.objects.exists())

    @override_settings(
        SESSION_SAVE_EVERY_REQUEST=True,
        AUTHENTICATION_BACKENDS=(
            "qc_tool.frontend.accounts.authentication.backends.MaintenanceBackend",
            "django.contrib.auth.backends.ModelBackend",
        ),
    )
    def test_legacy_hash_login_writes_no_sessions_last_login_or_authentication_signal(self):
        original_hash = PBKDF2PasswordHasher().encode(self.password, "maintenance-salt", iterations=1)
        get_user_model().objects.filter(pk=self.administrator.pk).update(password=original_hash)
        signals = []

        def observed_login(sender, **kwargs):
            signals.append(kwargs)

        user_logged_in.connect(observed_login, weak=False)
        self.addCleanup(user_logged_in.disconnect, observed_login)
        client, response = self.login(self.administrator)
        self.assertEqual(response.status_code, 302)
        self.assert_cookie_identity(client, self.administrator)
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], settings.SESSION_COOKIE_SAMESITE)
        self.assertLessEqual(int(cookie["max-age"]), 30 * 60)
        self.assertEqual(self.without_writes(lambda: client.get(reverse("admin_maintenance"))).status_code, 200)
        self.administrator.refresh_from_db()
        self.assertEqual(self.administrator.password, original_hash)
        self.assertIsNone(self.administrator.last_login)
        self.assertFalse(Session.objects.exists())
        self.assertEqual(signals, [])

    def test_only_administrators_can_manage_maintenance_after_signing_in(self):
        for user, expected in ((self.administrator, 200), (self.superuser, 200), (self.manager, 403)):
            with self.subTest(user=user.username):
                client, _response = self.login(user)
                response = self.without_writes(lambda: client.get(reverse("admin_maintenance")))
                self.assertEqual(response.status_code, expected)

    def test_signed_in_administrator_can_resume_ready_maintenance_without_sql_writes(self):
        ready = maintenance.advance(self.generation)
        self.assertEqual(ready["phase"], "ready")
        url = reverse("admin_maintenance")
        payload = {"action": "disable", "generation": ready["generation"]}

        manager, _response = self.login(self.manager)
        denied = self.without_writes(lambda: manager.post(
            url, payload, HTTP_X_CSRFTOKEN=manager.cookies[settings.CSRF_COOKIE_NAME].value,
        ))
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(maintenance.read_status()["enabled"])
        self.assertEqual(maintenance.read_status()["generation"], ready["generation"])

        administrator, _response = self.login(self.administrator, endpoint="admin:login")
        self.assert_cookie_identity(administrator, self.administrator)
        resumed = self.without_writes(lambda: administrator.post(
            url, payload, HTTP_X_CSRFTOKEN=administrator.cookies[settings.CSRF_COOKIE_NAME].value,
        ))
        self.assertContains(resumed, "Maintenance mode disabled.")
        status = maintenance.read_status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["phase"], "off")
        self.assertGreater(status["generation"], ready["generation"])
        self.assertFalse(Session.objects.exists())

    def test_operator_cookie_cannot_enable_database_mutations(self):
        for user in (self.administrator, self.manager):
            client, _response = self.login(user)
            for endpoint in ("account_settings", "change_password", "api_token_create", "product_upload", "admin:index"):
                with self.subTest(user=user.username, endpoint=endpoint):
                    response = self.without_writes(lambda: client.post(reverse(endpoint), {"first_name": "changed"}))
                    self.assertEqual(response.status_code, 503)

    def test_password_change_and_role_revocation_invalidate_operator_cookie(self):
        client, _response = self.login(self.administrator)
        self.administrator.set_password("new-password")
        self.administrator.save(update_fields=("password",))
        response = self.without_writes(lambda: client.get(reverse("products")))
        self.assertEqual(response.status_code, 302)
        client, _response = self.login(self.manager)
        self.manager.groups.remove(self.manager.groups.get(name=Role.PRODUCT_MANAGER.value))
        response = self.without_writes(lambda: client.get(reverse("products")))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Session.objects.exists())

    def test_tampered_and_expired_signed_cookie_cannot_authenticate(self):
        client, _response = self.login(self.administrator)
        original = client.cookies[settings.SESSION_COOKIE_NAME].value
        client.cookies[settings.SESSION_COOKIE_NAME] = original + "tampered"
        response = self.without_writes(lambda: client.get(reverse("products")))
        self.assertEqual(response.status_code, 302)
        client.cookies[settings.SESSION_COOKIE_NAME] = original
        with patch("django.core.signing.time.time", return_value=4_000_000_000):
            response = self.without_writes(lambda: client.get(reverse("products")))
        self.assertEqual(response.status_code, 302)

    def test_ended_maintenance_cookie_cannot_authorize_normal_database_changes(self):
        client, _response = self.login(self.administrator)
        session = self.assert_cookie_identity(client, self.administrator)
        self.assertEqual(session[GENERATION], self.generation)
        original = client.cookies[settings.SESSION_COOKIE_NAME].value
        csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value
        maintenance.advance(self.generation)
        maintenance.disable("isolated test", self.generation)

        response = self.without_writes(lambda: client.post(
            reverse("account_settings"), {"first_name": "unexpected change"},
            HTTP_X_CSRFTOKEN=csrf_token,
        ))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))
        self.assertNotIn(SESSION_KEY, cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value))
        self.administrator.refresh_from_db()
        self.assertNotEqual(self.administrator.first_name, "unexpected change")

        # Replaying the original signed credential cannot bypass expiry of its
        # maintenance window, even before the browser accepts the cleared one.
        client.cookies[settings.SESSION_COOKIE_NAME] = original
        page = self.without_writes(lambda: client.get(reverse("products")))
        self.assertEqual(page.status_code, 302)
        self.assertFalse(Session.objects.exists())

    def test_previous_generation_cookie_cannot_authenticate_in_a_new_maintenance_window(self):
        client, _response = self.login(self.manager)
        original = client.cookies[settings.SESSION_COOKIE_NAME].value
        maintenance.advance(self.generation)
        off = maintenance.disable("isolated test", self.generation)
        new_generation = maintenance.enable("new isolated window", off["generation"])["generation"]
        self.assertNotEqual(new_generation, self.generation)

        client.cookies[settings.SESSION_COOKIE_NAME] = original
        response = self.without_writes(lambda: client.get(reverse("products")))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(SESSION_KEY, cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value))
        self.assertFalse(Session.objects.exists())

    @override_settings(
        SESSION_SAVE_EVERY_REQUEST=True,
        AUTHENTICATION_BACKENDS=(
            "qc_tool.frontend.accounts.authentication.backends.MaintenanceBackend",
            "django.contrib.auth.backends.ModelBackend",
        ),
    )
    def test_opening_login_preserves_existing_legacy_database_session_and_browsing(self):
        for endpoint in ("login", "admin:login"):
            with self.subTest(endpoint=endpoint):
                client = Client(enforce_csrf_checks=True)
                client.force_login(self.viewer, backend="django.contrib.auth.backends.ModelBackend")
                session_key = client.cookies[settings.SESSION_COOKIE_NAME].value
                stored = Session.objects.get(session_key=session_key)
                original_session = (stored.session_data, stored.expire_date)
                self.viewer.refresh_from_db()
                original_last_login = self.viewer.last_login

                page = self.without_writes(lambda: client.get(reverse(endpoint)))
                self.assertEqual(page.status_code, 200)
                self.assertEqual(client.cookies[settings.SESSION_COOKIE_NAME].value, session_key)
                self.assertIsNone(cookie_session(session_key))
                products = self.without_writes(lambda: client.get(reverse("products")))
                self.assertEqual(products.status_code, 200)
                self.assertEqual(products.wsgi_request.user.pk, self.viewer.pk)
                stored.refresh_from_db()
                self.assertEqual((stored.session_data, stored.expire_date), original_session)
                self.viewer.refresh_from_db()
                self.assertEqual(self.viewer.last_login, original_last_login)

    @override_settings(AUTHENTICATION_BACKENDS=(
        "qc_tool.frontend.accounts.authentication.backends.MaintenanceBackend",
        "django.contrib.auth.backends.ModelBackend",
    ))
    def test_failed_maintenance_authentication_never_falls_through_to_hash_upgrading_backend(self):
        request = RequestFactory().post(reverse("login"))
        request.maintenance_active = True
        credentials = (
            {"username": self.manager.username, "password": "incorrect"},
            {"username": self.inactive.username, "password": self.password},
            {"username": "no-such-maintenance-user", "password": self.password},
            {"password": self.password},
            {"username": self.manager.username},
        )
        with patch("django.contrib.auth.backends.ModelBackend.authenticate") as normal_backend:
            for credential in credentials:
                with self.subTest(credentials=tuple(credential)):
                    self.assertIsNone(self.without_writes(lambda: authenticate(request, **credential)))
            normal_backend.assert_not_called()

    def test_external_next_is_rejected_on_both_login_routes(self):
        for endpoint, destination in (("login", "dashboard_home"), ("admin:login", "admin:index")):
            with self.subTest(endpoint=endpoint):
                _client, response = self.login(self.administrator, endpoint=endpoint,
                                               next_url="https://example.invalid/capture")
                self.assertRedirects(response, reverse(destination), fetch_redirect_response=False)

    @override_settings(CSRF_USE_SESSIONS=True)
    def test_session_backed_csrf_uses_cookie_only_and_normal_login_resumes_sql_sessions(self):
        client, response = self.login(self.manager)
        self.assertEqual(response.status_code, 302)
        self.assert_cookie_identity(client, self.manager)
        self.assertFalse(Session.objects.exists())
        maintenance.advance(self.generation)
        maintenance.disable("isolated test", self.generation)
        client, response = self.login(self.viewer, client=client, read_only=False)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value))
        self.assertEqual(Session.objects.count(), 1)
        self.viewer.refresh_from_db()
        self.assertIsNotNone(self.viewer.last_login)
