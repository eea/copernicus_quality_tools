"""API authentication runs against real frontend dispatch, without live hosts."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token


class DeliveryListAuthenticationTests(TestCase):
    def assert_bearer_challenge(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], 'Bearer realm="QC Tool API"')
        self.assertEqual(response.json()["code"], "authentication_required")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_anonymous_delivery_list_requires_bearer_credentials(self):
        self.assert_bearer_challenge(self.client.get(reverse("api_delivery_list")))

    def test_browser_session_does_not_replace_api_credentials(self):
        user = get_user_model().objects.create_superuser(username="session-only-api")
        self.client.force_login(user)
        self.assert_bearer_challenge(self.client.get(reverse("api_delivery_list")))

    def test_valid_bearer_without_delivery_permission_is_forbidden(self):
        user = get_user_model().objects.create_user(username="forbidden-api-reader")
        # Exercise a retained account without its required role; normal M2M
        # APIs restore that invariant automatically.
        user.groups.through.objects.filter(user_id=user.pk).delete()
        token = issue_personal_access_token(user, "Forbidden endpoint regression")
        response = self.client.get(reverse("api_delivery_list"),
                                   HTTP_AUTHORIZATION=f"Bearer {token.raw_token}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "permission_denied")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_authorized_bearer_reaches_delivery_list(self):
        user = get_user_model().objects.create_user(username="allowed-api-reader")
        token = issue_personal_access_token(user, "Allowed endpoint regression")
        response = self.client.get(reverse("api_delivery_list"),
                                   HTTP_AUTHORIZATION=f"Bearer {token.raw_token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deliveries"], [])

