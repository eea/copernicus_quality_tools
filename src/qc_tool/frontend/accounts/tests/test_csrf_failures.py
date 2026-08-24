from django.contrib.auth import get_user_model
from django.test import Client
from django.test import TestCase
from django.urls import reverse


class RouteAwareCsrfFailureTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_anonymous_private_session_data_failure_uses_authentication_json(self):
        response = self.client.post(reverse("delivery_delete"), {"ids": "1"})

        login_url = reverse("login")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "status": "error",
                "code": "authentication_required",
                "message": "Your session has expired. Please sign in again.",
                "login_url": login_url,
            },
        )
        self.assertEqual(response.headers["X-Login-URL"], login_url)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Cookie", response.headers["Vary"])

    def test_authenticated_private_session_data_failure_uses_csrf_json(self):
        user = get_user_model().objects.create_superuser(
            username="csrf-admin",
            email="csrf-admin@example.test",
            password="unused",
        )
        self.client.force_login(user)

        response = self.client.post(reverse("delivery_delete"), {"ids": "1"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {
                "status": "error",
                "code": "csrf_failed",
                "message": (
                    "Security verification failed. Refresh the page and try again."
                ),
            },
        )
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertIn("Cookie", response.headers["Vary"])

    def test_page_form_failure_retains_djangos_html_response(self):
        response = self.client.post(reverse("announcement"))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.headers["Content-Type"].startswith("text/html"))

    def test_api_key_route_remains_csrf_exempt(self):
        response = self.client.post(reverse("api_register_delivery"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(
            response.headers["WWW-Authenticate"],
            'Bearer realm="QC Tool API"',
        )
        self.assertNotEqual(response.json().get("code"), "csrf_failed")
