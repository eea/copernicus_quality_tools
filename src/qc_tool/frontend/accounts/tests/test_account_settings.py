from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.forms import AccountProfileForm
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


class AccountProfileFormTests(TestCase):
    def test_form_allowlists_only_safe_profile_fields(self):
        self.assertEqual(
            AccountProfileForm._meta.fields,
            ("first_name", "last_name", "email"),
        )

        form = AccountProfileForm()

        self.assertEqual(
            tuple(form.fields),
            ("first_name", "last_name", "email"),
        )


class AccountSettingsViewTests(TestCase):
    password = "correct-horse-battery-staple"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="settings-owner",
            password=self.password,
            first_name="Existing",
            last_name="User",
            email="existing@example.test",
        )
        self.url = reverse("account_settings")

    def remove_account_access(self):
        """Bypass role-preservation signals to exercise fail-closed policy."""

        self.user.groups.through.objects.filter(user_id=self.user.pk).delete()
        self.user.user_permissions.through.objects.filter(
            user_id=self.user.pk,
        ).delete()

    def grant_permission(self, permission):
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type=capability_content_type(),
                codename=permission.value,
            )
        )

    def test_anonymous_requests_redirect_without_mutating_profile(self):
        response = self.client.post(
            self.url,
            {
                "first_name": "Attacker",
                "last_name": "Changed",
                "email": "attacker@example.test",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={self.url}",
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Existing")

    def test_settings_page_displays_immutable_username_and_safe_form(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/settings/index.html")
        self.assertContains(response, "Account settings")
        self.assertContains(response, "site-nav-user--active")
        self.assertContains(response, 'id="account-username"')
        self.assertContains(response, 'value="settings-owner"')
        self.assertContains(response, "readonly")
        self.assertNotContains(response, 'name="username"')
        self.assertContains(response, 'name="first_name"')
        self.assertContains(response, 'name="last_name"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'id="api-tokens"')
        self.assertContains(response, "0 active tokens")
        self.assertContains(response, "No active tokens")
        self.assertContains(response, "Create token")
        self.assertNotContains(response, "qct_")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("Cookie", response["Vary"])

    def test_valid_profile_update_uses_post_redirect_get(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "first_name": "Updated",
                "last_name": "Person",
                "email": "Person@EXAMPLE.TEST",
            },
        )

        self.assertRedirects(
            response,
            self.url,
            fetch_redirect_response=False,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.last_name, "Person")
        self.assertEqual(self.user.email, "Person@example.test")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        follow_up = self.client.get(self.url)
        self.assertContains(follow_up, "Your profile details were updated.")

    def test_profile_update_does_not_overwrite_concurrent_security_changes(self):
        self.client.force_login(self.user)
        original_is_valid = AccountProfileForm.is_valid

        def validate_after_security_change(form):
            is_valid = original_is_valid(form)
            get_user_model().objects.filter(pk=self.user.pk).update(
                is_active=False,
                is_staff=True,
            )
            return is_valid

        with patch.object(
            AccountProfileForm,
            "is_valid",
            validate_after_security_change,
        ):
            response = self.client.post(
                self.url,
                {
                    "first_name": "Concurrent",
                    "last_name": "Update",
                    "email": "concurrent@example.test",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.is_staff)
        self.assertEqual(self.user.first_name, "Concurrent")

    def test_forged_access_and_identity_fields_are_ignored(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "first_name": "Safe",
                "last_name": "Update",
                "email": "safe@example.test",
                "username": "renamed-owner",
                "is_active": "",
                "is_staff": "on",
                "is_superuser": "on",
                "groups": ["99999"],
                "user_permissions": ["99999"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "settings-owner")
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(self.user.first_name, "Safe")

    def test_invalid_email_rerenders_without_saving_any_profile_field(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {
                "first_name": "Should not save",
                "last_name": "Invalid",
                "email": "not-an-email",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid email address.")
        self.assertContains(response, 'aria-describedby="id_email_error"')
        self.assertContains(response, 'id="id_email_error"')
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Existing")
        self.assertEqual(self.user.last_name, "User")
        self.assertEqual(self.user.email, "existing@example.test")

    def test_manage_own_account_permission_is_required(self):
        self.client.force_login(self.user)
        self.remove_account_access()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_direct_manage_own_account_permission_is_sufficient(self):
        self.client.force_login(self.user)
        self.remove_account_access()
        self.grant_permission(AccountPermission.MANAGE_OWN_ACCOUNT)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile details")
        self.assertNotContains(response, 'id="api-tokens"')
        self.assertTemplateUsed(response, "dashboard/shared/breadcrumbs.html")
        self.assertContains(
            response,
            '<a href="https://github.com/eea/copernicus_quality_tools/wiki">'
            'CLMS QC Tool documentation</a>',
            html=True,
        )

    def test_api_permission_alone_opens_only_token_settings(self):
        self.client.force_login(self.user)
        self.remove_account_access()
        self.grant_permission(AccountPermission.MANAGE_API_CREDENTIAL)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Profile details")
        self.assertNotContains(response, 'name="first_name"')
        self.assertContains(response, 'id="api-tokens"')
        self.assertContains(response, "Create token")

    def test_api_only_account_cannot_post_profile_fields(self):
        self.client.force_login(self.user)
        self.remove_account_access()
        self.grant_permission(AccountPermission.MANAGE_API_CREDENTIAL)

        response = self.client.post(
            self.url,
            {
                "first_name": "Forbidden",
                "last_name": "Update",
                "email": "forbidden@example.test",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Existing")

    def test_profile_update_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        rejected = csrf_client.post(
            self.url,
            {
                "first_name": "Rejected",
                "last_name": "Request",
                "email": "rejected@example.test",
            },
        )

        self.assertEqual(rejected.status_code, 403)
        token = _get_new_csrf_string()
        csrf_client.cookies["csrftoken"] = token
        accepted = csrf_client.post(
            self.url,
            {
                "first_name": "Accepted",
                "last_name": "Request",
                "email": "accepted@example.test",
            },
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(accepted.status_code, 302)

    def test_unsupported_http_method_does_not_mutate_profile(self):
        self.client.force_login(self.user)

        response = self.client.put(
            self.url,
            data="first_name=Unexpected",
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 405)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Existing")

    def test_named_token_shows_status_without_secret_or_digest(self):
        issued = issue_personal_access_token(self.user, "Weather service")
        stored_digest = PersonalAccessToken.objects.get(
            pk=issued.token.pk,
        ).secret_digest
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertContains(response, "1 active token")
        self.assertContains(response, "Weather service")
        self.assertContains(response, "Delete token")
        self.assertNotContains(response, issued.raw_token)
        self.assertNotContains(response, stored_digest)
