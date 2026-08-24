import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import TestCase

from qc_tool.frontend.accounts.authentication.api_keys import (
    API_KEY_DIGEST_LENGTH,
)
from qc_tool.frontend.accounts.authentication.api_keys import API_KEY_LENGTH
from qc_tool.frontend.accounts.authentication.api_keys import API_KEY_PREFIX
from qc_tool.frontend.accounts.authentication.api_keys import (
    ApiKeyAuthenticationError,
)
from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_key,
)
from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_request,
)
from qc_tool.frontend.accounts.authentication.api_keys import digest_api_key
from qc_tool.frontend.accounts.authentication.api_keys import generate_api_key
from qc_tool.frontend.accounts.authentication.api_keys import has_api_key
from qc_tool.frontend.accounts.authentication.api_keys import (
    is_api_key_digest,
)
from qc_tool.frontend.accounts.authentication.api_keys import (
    issue_or_rotate_api_key,
)
from qc_tool.frontend.accounts.authentication.api_keys import revoke_api_key
from qc_tool.frontend.accounts.models import ApiUser


def api_key(character="A"):
    return API_KEY_PREFIX + (character * (API_KEY_LENGTH - len(API_KEY_PREFIX)))


class ApiKeyTests(TestCase):
    def setUp(self):
        self.users = get_user_model().objects
        self.request_factory = RequestFactory()

    def create_user(self, username, *, is_active=True):
        return self.users.create_user(username=username, is_active=is_active)

    @patch(
        "qc_tool.frontend.accounts.authentication.api_keys.secrets.token_urlsafe",
        return_value="A" * 43,
    )
    def test_generation_uses_256_bits_and_a_namespaced_prefix(self, token_urlsafe):
        raw_key = generate_api_key()

        self.assertEqual(raw_key, api_key())
        self.assertEqual(len(raw_key), API_KEY_LENGTH)
        token_urlsafe.assert_called_once_with(32)

    def test_digest_is_versioned_exact_and_does_not_contain_raw_secret(self):
        raw_key = api_key()
        stored_value = digest_api_key(raw_key)

        expected = hashlib.sha256(raw_key.encode("ascii")).hexdigest()
        self.assertEqual(stored_value, f"sha256${expected}")
        self.assertEqual(len(stored_value), API_KEY_DIGEST_LENGTH)
        self.assertNotIn(raw_key, stored_value)
        self.assertTrue(is_api_key_digest(stored_value))

    def test_digest_rejects_values_the_service_did_not_issue(self):
        for value in (
            "",
            "legacy-key",
            "qct_short",
            api_key() + "=",
            "QCT_" + ("A" * 43),
            "qct_" + ("é" * 43),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    digest_api_key(value)

    @patch(
        "qc_tool.frontend.accounts.authentication.api_keys.generate_api_key",
        side_effect=(api_key("A"), api_key("B")),
    )
    def test_issue_then_rotate_overwrites_one_row_and_returns_secret_once(
        self,
        generate,
    ):
        user = self.create_user("api-user")

        first = issue_or_rotate_api_key(user)
        credential = ApiUser.objects.get(user=user)
        first_digest = credential.api_key
        second = issue_or_rotate_api_key(user)
        credential.refresh_from_db()

        self.assertEqual(first, api_key("A"))
        self.assertEqual(second, api_key("B"))
        self.assertEqual(credential.api_key, digest_api_key(second))
        self.assertNotEqual(credential.api_key, second)
        self.assertNotEqual(credential.api_key, first_digest)
        self.assertEqual(ApiUser.objects.filter(user=user).count(), 1)
        self.assertIsNone(authenticate_api_key(first))
        self.assertEqual(authenticate_api_key(second), user)
        self.assertEqual(generate.call_count, 2)

    def test_issue_rejects_an_unsaved_user(self):
        user = get_user_model()(username="unsaved")

        with self.assertRaises(ValueError):
            issue_or_rotate_api_key(user)

    def test_revoke_is_idempotent_and_status_requires_current_digest_format(self):
        user = self.create_user("revoke-user")
        raw_key = issue_or_rotate_api_key(user)

        self.assertTrue(has_api_key(user))
        self.assertTrue(revoke_api_key(user))
        self.assertFalse(revoke_api_key(user))
        self.assertFalse(has_api_key(user))
        self.assertIsNone(authenticate_api_key(raw_key))

        ApiUser.objects.create(user=user, api_key="PLAINTEXT-LEGACY")
        self.assertFalse(has_api_key(user))
        self.assertIsNone(authenticate_api_key("PLAINTEXT-LEGACY"))

    def test_authentication_rejects_inactive_and_duplicate_digests(self):
        active = self.create_user("active-api-user")
        inactive = self.create_user("inactive-api-user", is_active=False)
        active_key = api_key("A")
        inactive_key = api_key("I")
        duplicate_key = api_key("D")
        ApiUser.objects.create(user=active, api_key=digest_api_key(active_key))
        ApiUser.objects.create(
            user=inactive,
            api_key=digest_api_key(inactive_key),
        )
        duplicate_digest = digest_api_key(duplicate_key)
        ApiUser.objects.create(
            user=self.create_user("duplicate-one"),
            api_key=duplicate_digest,
        )
        ApiUser.objects.create(
            user=self.create_user("duplicate-two"),
            api_key=duplicate_digest,
        )

        self.assertEqual(authenticate_api_key(active_key), active)
        self.assertIsNone(authenticate_api_key(inactive_key))
        self.assertIsNone(authenticate_api_key(duplicate_key))
        self.assertIsNone(authenticate_api_key(""))

    def test_request_authentication_accepts_only_exact_bearer_header(self):
        user = self.create_user("request-api-user")
        raw_key = api_key("R")
        ApiUser.objects.create(user=user, api_key=digest_api_key(raw_key))

        result = authenticate_api_request(
            self.request_factory.get(
                "/api/resource",
                HTTP_AUTHORIZATION=f"Bearer {raw_key}",
            )
        )

        self.assertTrue(result.is_authenticated)
        self.assertEqual(result.user, user)
        self.assertIsNone(result.error)

        lowercase_scheme = authenticate_api_request(
            self.request_factory.get(
                "/api/resource",
                HTTP_AUTHORIZATION=f"bEaReR {raw_key}",
            )
        )
        self.assertTrue(lowercase_scheme.is_authenticated)
        self.assertEqual(lowercase_scheme.user, user)

    def test_request_authentication_distinguishes_missing_credentials(self):
        result = authenticate_api_request(
            self.request_factory.get("/api/resource")
        )

        self.assertFalse(result.is_authenticated)
        self.assertEqual(result.error, ApiKeyAuthenticationError.MISSING)

    def test_request_authentication_rejects_any_query_credential(self):
        raw_key = api_key("Q")
        for query, header in (
            ({"apikey": raw_key}, None),
            ({"apikey": ""}, None),
            ({"apikey": raw_key}, f"Bearer {raw_key}"),
            ({"ApiKey": raw_key}, f"Bearer {raw_key}"),
        ):
            with self.subTest(query=query, header=header):
                request = self.request_factory.get(
                    "/api/resource",
                    query,
                    **({"HTTP_AUTHORIZATION": header} if header else {}),
                )
                result = authenticate_api_request(request)
                self.assertEqual(
                    result.error,
                    ApiKeyAuthenticationError.QUERY_PARAMETER,
                )

    def test_request_authentication_rejects_malformed_or_unbounded_headers(self):
        raw_key = api_key("M")
        headers = (
            "",
            raw_key,
            f"Bearer  {raw_key}",
            f"Bearer\t{raw_key}",
            f"Basic {raw_key}",
            "Bearer qct_short",
            f"Bearer {raw_key}=",
            "Bearer qct_" + ("é" * 43),
            "Bearer " + ("A" * 200),
        )
        for authorization in headers:
            with self.subTest(authorization=authorization):
                result = authenticate_api_request(
                    self.request_factory.get(
                        "/api/resource",
                        HTTP_AUTHORIZATION=authorization,
                    )
                )
                self.assertEqual(
                    result.error,
                    ApiKeyAuthenticationError.MALFORMED,
                )

    def test_request_authentication_rejects_well_formed_unknown_key(self):
        result = authenticate_api_request(
            self.request_factory.get(
                "/api/resource",
                HTTP_AUTHORIZATION=f"Bearer {api_key('X')}",
            )
        )

        self.assertEqual(result.error, ApiKeyAuthenticationError.INVALID)
