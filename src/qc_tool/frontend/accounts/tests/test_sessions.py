from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth import get_user_model
from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse


class BrowserSessionFlowTests(TestCase):
    password = "correct-horse-battery-staple"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="session-user",
            password=self.password,
        )

    def csrf_client(self):
        return Client(enforce_csrf_checks=True)

    def csrf_token_from(self, client, url):
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        return response, client.cookies[settings.CSRF_COOKIE_NAME].value

    def login_through_view(self, client, *, username=None, password=None, next_url=""):
        login_url = reverse("login")
        _response, csrf_token = self.csrf_token_from(client, login_url)
        return client.post(
            login_url,
            {
                "username": username or self.user.get_username(),
                "password": password or self.password,
                "next": next_url,
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

    def test_login_uses_django_view_and_rotates_the_session_key(self):
        client = self.csrf_client()
        pre_login_session = client.session
        pre_login_session["pre_login_value"] = "preserved"
        pre_login_session.save()
        pre_login_key = pre_login_session.session_key

        response = self.login_through_view(client)

        self.assertRedirects(
            response,
            reverse("dashboard_home"),
            fetch_redirect_response=False,
        )
        self.assertEqual(client.session[SESSION_KEY], str(self.user.pk))
        self.assertEqual(client.session["pre_login_value"], "preserved")
        self.assertNotEqual(client.session.session_key, pre_login_key)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

        session_cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session_cookie["httponly"])
        self.assertEqual(session_cookie["samesite"], "Lax")

    def test_login_requires_csrf_and_rejects_invalid_or_inactive_users(self):
        client = self.csrf_client()
        tokenless = client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password},
        )
        self.assertEqual(tokenless.status_code, 403)

        wrong_password = self.login_through_view(
            client,
            password="not-the-password",
        )
        self.assertEqual(wrong_password.status_code, 200)
        self.assertNotIn(SESSION_KEY, client.session)

        self.user.is_active = False
        self.user.save(update_fields=("is_active",))
        inactive = self.login_through_view(client)
        self.assertEqual(inactive.status_code, 200)
        self.assertNotIn(SESSION_KEY, client.session)

    @override_settings(
        AUTHENTICATION_BACKENDS=(
            "qc_tool.frontend.accounts.authentication.backends."
            "CaseInsensitiveBackend",
        )
    )
    def test_case_insensitive_backend_works_through_the_login_view(self):
        client = self.csrf_client()

        response = self.login_through_view(
            client,
            username=self.user.username.upper(),
        )

        self.assertRedirects(
            response,
            reverse("dashboard_home"),
            fetch_redirect_response=False,
        )
        self.assertEqual(client.session[SESSION_KEY], str(self.user.pk))

    def test_login_accepts_local_next_and_rejects_external_redirects(self):
        local_client = self.csrf_client()
        local_response = self.login_through_view(
            local_client,
            next_url=reverse("change_password"),
        )
        self.assertRedirects(
            local_response,
            reverse("change_password"),
            fetch_redirect_response=False,
        )

        external_client = self.csrf_client()
        external_response = self.login_through_view(
            external_client,
            next_url="https://example.invalid/collect-session",
        )
        self.assertRedirects(
            external_response,
            reverse("dashboard_home"),
            fetch_redirect_response=False,
        )

    def test_logout_is_csrf_protected_post_and_flushes_authentication(self):
        client = self.csrf_client()
        self.login_through_view(client)
        self.assertIn(SESSION_KEY, client.session)

        logout_url = reverse("logout")
        self.assertEqual(client.get(logout_url).status_code, 405)

        tokenless = client.post(logout_url)
        self.assertEqual(tokenless.status_code, 403)
        self.assertIn(SESSION_KEY, client.session)

        csrf_token = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post(logout_url, HTTP_X_CSRFTOKEN=csrf_token)

        self.assertRedirects(
            response,
            reverse("login"),
            fetch_redirect_response=False,
        )
        self.assertNotIn(SESSION_KEY, client.session)

        protected = client.get(reverse("deliveries"))
        self.assertEqual(protected.status_code, 302)
        self.assertTrue(protected.url.startswith(reverse("login")))

    def test_authenticated_navigation_renders_one_shared_logout_form(self):
        client = self.csrf_client()
        self.login_through_view(client)
        logout_url = reverse("logout")

        for route_name in (
            "dashboard_home",
            "deliveries",
            "file_upload",
            "change_password",
        ):
            with self.subTest(route_name=route_name):
                response = client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f'<form method="post" action="{logout_url}">',
                    count=1,
                )
                self.assertNotContains(response, f'href="{logout_url}')
