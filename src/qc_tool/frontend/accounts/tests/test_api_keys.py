import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
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
    authenticate_personal_access_token,
)
from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_request,
)
from qc_tool.frontend.accounts.authentication.api_keys import digest_api_key
from qc_tool.frontend.accounts.authentication.api_keys import generate_api_key
from qc_tool.frontend.accounts.authentication.api_keys import (
    is_api_key_digest,
)
from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import (
    delete_personal_access_token,
)
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


def api_key(character="A"):
    return API_KEY_PREFIX + (character * (API_KEY_LENGTH - len(API_KEY_PREFIX)))


class ApiKeyTests(TestCase):
    def setUp(self):
        self.users = get_user_model().objects
        self.request_factory = RequestFactory()

    def create_user(self, username, *, is_active=True):
        return self.users.create_user(username=username, is_active=is_active)

    def authenticate_request(self, raw_token):
        return authenticate_api_request(
            self.request_factory.get(
                "/api/resource",
                HTTP_AUTHORIZATION=f"Bearer {raw_token}",
            )
        )

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

    def test_two_named_tokens_are_independent_and_deleting_one_preserves_other(self):
        user = self.create_user("multi-token-user")
        first = issue_personal_access_token(user, "Automation")
        second = issue_personal_access_token(user, "Desktop client")

        self.assertNotEqual(first.raw_token, second.raw_token)
        self.assertEqual(
            set(
                PersonalAccessToken.objects.filter(user=user).values_list(
                    "name",
                    flat=True,
                )
            ),
            {"Automation", "Desktop client"},
        )
        self.assertEqual(authenticate_personal_access_token(first.raw_token).user, user)
        self.assertEqual(authenticate_personal_access_token(second.raw_token).user, user)

        deleted_name = delete_personal_access_token(user, first.token.pk)

        self.assertEqual(deleted_name, "Automation")
        self.assertIsNone(authenticate_personal_access_token(first.raw_token))
        self.assertEqual(authenticate_personal_access_token(second.raw_token).user, user)
        self.assertTrue(
            PersonalAccessToken.objects.filter(pk=second.token.pk).exists()
        )

    def test_revoked_live_permission_immediately_narrows_an_existing_token(self):
        user = self.create_user("revoked-live-permission")
        issued = issue_personal_access_token(user, "Before revocation")
        self.assertIn(
            AccountPermission.RUN_QC,
            self.authenticate_request(issued.raw_token).access.permissions,
        )

        user.groups.through.objects.filter(user_id=user.pk).delete()
        result = self.authenticate_request(issued.raw_token)

        self.assertTrue(result.is_authenticated)
        self.assertEqual(result.user, user)
        self.assertEqual(result.token.pk, issued.token.pk)
        self.assertNotIn(AccountPermission.RUN_QC, result.access.permissions)

    def test_later_permission_and_scope_grants_do_not_broaden_old_token(self):
        user = self.create_user("later-grants")
        user.groups.through.objects.filter(user_id=user.pk).delete()
        view_permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.VIEW_DELIVERIES.value,
        )
        run_permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.RUN_QC.value,
        )
        user.user_permissions.add(view_permission)
        UserProductGrant.objects.create(
            user=user,
            product_ident="general_raster",
        )
        issued = issue_personal_access_token(user, "Narrow snapshot")

        user.user_permissions.add(run_permission)
        UserProductGrant.objects.create(
            user=user,
            product_ident="later_product",
        )
        result = self.authenticate_request(issued.raw_token)

        self.assertTrue(result.is_authenticated)
        self.assertIn(
            AccountPermission.VIEW_DELIVERIES,
            result.access.permissions,
        )
        self.assertNotIn(AccountPermission.RUN_QC, result.access.permissions)
        self.assertEqual(result.access.product_idents, {"general_raster"})

    def test_malformed_token_snapshots_authenticate_identity_but_deny_access(self):
        user = self.create_user("malformed-snapshot")
        issued = issue_personal_access_token(user, "Corrupt snapshot")
        PersonalAccessToken.objects.filter(pk=issued.token.pk).update(
            permission_snapshot={"run_qc": True},
            role_snapshot=["not-a-role"],
            product_idents_snapshot={"general_raster": True},
        )

        result = self.authenticate_request(issued.raw_token)

        self.assertTrue(result.is_authenticated)
        self.assertEqual(result.access.permissions, frozenset())
        self.assertEqual(result.access.roles, frozenset())
        self.assertEqual(result.access.product_idents, frozenset())
        self.assertFalse(result.access.is_administrator)

    def test_authentication_rejects_an_inactive_token_owner(self):
        user = self.create_user("inactive-api-user")
        issued = issue_personal_access_token(user, "Inactive owner")
        user.is_active = False
        user.save(update_fields=("is_active",))

        self.assertIsNone(authenticate_personal_access_token(issued.raw_token))
        self.assertEqual(
            self.authenticate_request(issued.raw_token).error,
            ApiKeyAuthenticationError.INVALID,
        )

    def test_successful_authentication_records_last_use_without_exposing_secret(self):
        user = self.create_user("token-activity")
        issued = issue_personal_access_token(user, "Activity tracking")
        self.assertIsNone(issued.token.last_used_at)

        result = self.authenticate_request(issued.raw_token)

        issued.token.refresh_from_db()
        self.assertTrue(result.is_authenticated)
        self.assertIsNotNone(issued.token.last_used_at)
        self.assertNotEqual(issued.token.secret_digest, issued.raw_token)

    def test_request_authentication_accepts_only_exact_bearer_header(self):
        user = self.create_user("request-api-user")
        issued = issue_personal_access_token(user, "Request token")

        result = self.authenticate_request(issued.raw_token)

        self.assertTrue(result.is_authenticated)
        self.assertEqual(result.user, user)
        self.assertEqual(result.token.pk, issued.token.pk)
        self.assertIsNotNone(result.access)
        self.assertIsNone(result.error)

        lowercase_scheme = authenticate_api_request(
            self.request_factory.get(
                "/api/resource",
                HTTP_AUTHORIZATION=f"bEaReR {issued.raw_token}",
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
        result = self.authenticate_request(api_key("X"))

        self.assertEqual(result.error, ApiKeyAuthenticationError.INVALID)
