import string
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase

from qc_tool.frontend.accounts.authentication.api_keys import API_KEY_LENGTH
from qc_tool.frontend.accounts.authentication.api_keys import authenticate_api_key
from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_request,
)
from qc_tool.frontend.accounts.authentication.api_keys import generate_api_key
from qc_tool.frontend.accounts.authentication.api_keys import get_or_create_api_key
from qc_tool.frontend.accounts.models import ApiUser


class ApiKeyTests(TestCase):
    def setUp(self):
        self.users = get_user_model().objects

    def create_user(self, username, *, is_active=True):
        return self.users.create_user(username=username, is_active=is_active)

    @patch(
        "qc_tool.frontend.accounts.authentication.api_keys.secrets.choice",
        return_value="A",
    )
    def test_generation_uses_the_secure_choice_contract(self, choice):
        api_key = generate_api_key()

        self.assertEqual(api_key, "A" * API_KEY_LENGTH)
        self.assertEqual(choice.call_count, API_KEY_LENGTH)
        self.assertTrue(set(api_key) <= set(string.ascii_uppercase + string.digits))

    @patch(
        "qc_tool.frontend.accounts.authentication.api_keys.generate_api_key",
        return_value="A" * API_KEY_LENGTH,
    )
    def test_provisioning_creates_once_and_reuses_existing_key(self, generate):
        user = self.create_user("api-user")

        first = get_or_create_api_key(user)
        second = get_or_create_api_key(user)

        self.assertEqual(first, "A" * API_KEY_LENGTH)
        self.assertEqual(second, first)
        self.assertEqual(ApiUser.objects.filter(user=user).count(), 1)
        generate.assert_called_once_with()

    @patch(
        "qc_tool.frontend.accounts.authentication.api_keys.generate_api_key",
        side_effect=["C" * API_KEY_LENGTH, "U" * API_KEY_LENGTH],
    )
    def test_provisioning_retries_a_key_collision(self, generate):
        ApiUser.objects.create(
            user=self.create_user("existing-api-user"),
            api_key="C" * API_KEY_LENGTH,
        )
        user = self.create_user("new-api-user")

        api_key = get_or_create_api_key(user)

        self.assertEqual(api_key, "U" * API_KEY_LENGTH)
        self.assertEqual(generate.call_count, 2)

    def test_authentication_rejects_inactive_and_duplicate_credentials(self):
        active = self.create_user("active-api-user")
        inactive = self.create_user("inactive-api-user", is_active=False)
        ApiUser.objects.create(user=active, api_key="ACTIVE")
        ApiUser.objects.create(user=inactive, api_key="INACTIVE")
        ApiUser.objects.create(
            user=self.create_user("duplicate-one"),
            api_key="DUPLICATE",
        )
        ApiUser.objects.create(
            user=self.create_user("duplicate-two"),
            api_key="DUPLICATE",
        )

        self.assertEqual(authenticate_api_key("ACTIVE"), active)
        self.assertIsNone(authenticate_api_key("INACTIVE"))
        self.assertIsNone(authenticate_api_key("DUPLICATE"))
        self.assertIsNone(authenticate_api_key(""))

    def test_request_authentication_preserves_the_legacy_query_contract(self):
        user = self.create_user("request-api-user")
        ApiUser.objects.create(user=user, api_key="REQUEST-KEY")
        request_factory = RequestFactory()

        authenticated, message = authenticate_api_request(
            request_factory.get("/api/resource", {"apikey": "REQUEST-KEY"})
        )
        missing_user, missing_message = authenticate_api_request(
            request_factory.get("/api/resource")
        )

        self.assertEqual(authenticated, user)
        self.assertEqual(message, "ok")
        self.assertIsNone(missing_user)
        self.assertEqual(missing_message, "api key was not provided")
