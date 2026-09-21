import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_personal_access_token,
)
from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


class ApiCredentialViewTests(TestCase):
    def setUp(self):
        self.password = "correct horse battery staple"
        self.user = get_user_model().objects.create_user(
            username="credential-owner",
            password=self.password,
        )
        self.create_url = reverse("api_token_create")

    def delete_url(self, token):
        return reverse("api_token_delete", args=(token.pk,))

    def post_create(self, *, name="Desktop client", password=None, client=None):
        return (client or self.client).post(
            self.create_url,
            {
                "name": name,
                "current_password": self.password
                if password is None
                else password,
            },
        )

    def test_anonymous_user_is_redirected_before_token_operations(self):
        response = self.post_create()
        delete_url = reverse("api_token_delete", args=(999,))
        delete_response = self.client.post(delete_url)

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={self.create_url}",
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            delete_response,
            f"{reverse('login')}?next={delete_url}",
            fetch_redirect_response=False,
        )
        self.assertFalse(
            PersonalAccessToken.objects.filter(user=self.user).exists()
        )

    def test_lifecycle_views_are_post_only_and_get_does_not_mutate(self):
        self.client.force_login(self.user)
        issued = issue_personal_access_token(self.user, "Existing")

        create_response = self.client.get(self.create_url)
        delete_response = self.client.get(self.delete_url(issued.token))

        self.assertEqual(create_response.status_code, 405)
        self.assertEqual(delete_response.status_code, 405)
        self.assertTrue(
            PersonalAccessToken.objects.filter(pk=issued.token.pk).exists()
        )

    def test_creation_requires_the_current_password(self):
        self.client.force_login(self.user)

        for password in ("", "incorrect password"):
            with self.subTest(password=password):
                response = self.post_create(password=password)
                self.assertEqual(response.status_code, 400)
                self.assertTemplateUsed(
                    response,
                    "accounts/settings/index.html",
                )
                self.assertContains(response, "Current password", status_code=400)
                self.assertNotContains(
                    response,
                    password or self.password,
                    status_code=400,
                )
                self.assertContains(
                    response,
                    'aria-describedby="id_current_password_helptext '
                    'id_current_password_error"',
                    status_code=400,
                )
                self.assertEqual(
                    response.content.count(
                        b'id="id_current_password_error"'
                    ),
                    1,
                )

        self.assertFalse(
            PersonalAccessToken.objects.filter(user=self.user).exists()
        )

    def test_create_displays_secret_once_and_stores_only_its_digest(self):
        self.client.force_login(self.user)

        response = self.post_create(name="Delivery automation")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "accounts/api_credentials/issued.html",
        )
        raw_token = response.context["raw_token"]
        token = PersonalAccessToken.objects.get(user=self.user)
        self.assertRegex(raw_token, re.compile(r"qct_[A-Za-z0-9_-]{43}\Z"))
        self.assertRegex(
            token.secret_digest,
            re.compile(r"sha256\$[0-9a-f]{64}\Z"),
        )
        self.assertEqual(token.name, "Delivery automation")
        self.assertNotEqual(token.secret_digest, raw_token)
        self.assertContains(response, raw_token)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            response["X-Robots-Tag"],
            "noindex, nofollow, noarchive",
        )
        self.assertNotIn(raw_token, self.client.session.values())
        self.assertContains(
            response,
            "Copy “Delivery automation” token now",
        )
        self.assertNotContains(response, "credential-issued__eyebrow")
        self.assertContains(response, "#api-token")
        self.assertNotContains(response, "#key")
        self.assertContains(response, reverse("api_homepage"))
        self.assertContains(
            response,
            f'{reverse("account_settings")}#api-tokens',
        )

        settings_response = self.client.get(reverse("account_settings"))
        self.assertNotContains(settings_response, raw_token)
        self.assertNotContains(settings_response, token.secret_digest)

    def test_user_can_create_multiple_independently_named_tokens(self):
        self.client.force_login(self.user)

        first_response = self.post_create(name="Automation")
        second_response = self.post_create(name="Desktop")
        first = first_response.context["raw_token"]
        second = second_response.context["raw_token"]

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertNotEqual(first, second)
        self.assertEqual(
            set(
                PersonalAccessToken.objects.filter(user=self.user).values_list(
                    "name",
                    flat=True,
                )
            ),
            {"Automation", "Desktop"},
        )
        self.assertEqual(authenticate_personal_access_token(first).user, self.user)
        self.assertEqual(authenticate_personal_access_token(second).user, self.user)

    def test_duplicate_names_are_rejected_case_insensitively(self):
        self.client.force_login(self.user)
        first = self.post_create(name="Desktop")

        duplicate = self.post_create(name=" desktop ")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)
        self.assertContains(
            duplicate,
            "token names must be unique",
            status_code=400,
        )
        self.assertEqual(
            PersonalAccessToken.objects.filter(user=self.user).count(),
            1,
        )

    def test_delete_is_owner_scoped_and_removes_only_the_selected_token(self):
        other = get_user_model().objects.create_user(username="other-owner")
        first = issue_personal_access_token(self.user, "First")
        second = issue_personal_access_token(self.user, "Second")
        foreign = issue_personal_access_token(other, "Foreign")
        self.client.force_login(self.user)

        forged = self.client.post(self.delete_url(foreign.token))

        self.assertEqual(forged.status_code, 404)
        self.assertTrue(
            PersonalAccessToken.objects.filter(pk=foreign.token.pk).exists()
        )

        deleted = self.client.post(
            self.delete_url(first.token),
            {"next": "https://attacker.example/"},
        )

        self.assertRedirects(
            deleted,
            f"{reverse('account_settings')}#api-tokens",
            fetch_redirect_response=False,
        )
        self.assertIsNone(authenticate_personal_access_token(first.raw_token))
        self.assertEqual(authenticate_personal_access_token(second.raw_token).user, self.user)
        self.assertEqual(authenticate_personal_access_token(foreign.raw_token).user, other)
        self.assertEqual(deleted["Cache-Control"], "private, no-store")
        self.assertEqual(deleted["Referrer-Policy"], "no-referrer")

    def test_permission_is_checked_before_create_or_delete(self):
        issued = issue_personal_access_token(self.user, "Protected")
        self.client.force_login(self.user)
        self.user.groups.through.objects.filter(user_id=self.user.pk).delete()
        self.user.user_permissions.through.objects.filter(
            user_id=self.user.pk,
        ).delete()

        create_response = self.post_create()
        delete_response = self.client.post(self.delete_url(issued.token))

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(
            PersonalAccessToken.objects.filter(pk=issued.token.pk).exists()
        )

    def test_direct_api_permission_has_a_complete_management_flow(self):
        self.client.force_login(self.user)
        self.user.groups.through.objects.filter(user_id=self.user.pk).delete()
        self.user.user_permissions.through.objects.filter(
            user_id=self.user.pk,
        ).delete()
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type=capability_content_type(),
                codename=AccountPermission.MANAGE_API_CREDENTIAL.value,
            )
        )

        settings_response = self.client.get(reverse("account_settings"))
        issued_response = self.post_create(name="Direct permission")

        self.assertEqual(settings_response.status_code, 200)
        self.assertContains(settings_response, 'id="api-tokens"')
        self.assertNotContains(settings_response, "Profile details")
        self.assertEqual(issued_response.status_code, 200)
        self.assertTrue(
            PersonalAccessToken.objects.filter(user=self.user).exists()
        )

    def test_settings_lists_safe_named_token_metadata_without_secret_digest(self):
        escaped_name = '<script>alert("token")</script>'
        issued = issue_personal_access_token(self.user, escaped_name)
        self.client.force_login(self.user)

        response = self.client.get(reverse("account_settings"))

        issued.token.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="api-tokens"')
        self.assertContains(response, "1 active token")
        self.assertContains(
            response,
            "&lt;script&gt;alert(&quot;token&quot;)&lt;/script&gt;",
        )
        self.assertNotContains(response, escaped_name)
        self.assertNotContains(response, issued.raw_token)
        self.assertNotContains(response, issued.token.secret_digest)
        self.assertContains(response, issued.token.token_hint)
        self.assertContains(response, self.delete_url(issued.token))
        self.assertContains(response, "accounts/css/api-tokens.css")
        self.assertContains(response, "#api-token")
        self.assertNotContains(response, "#key")
        self.assertContains(response, reverse("api_homepage"))
        self.assertContains(response, "Created")
        self.assertContains(response, "Last used")
        self.assertContains(response, "Never")
        self.assertContains(response, "View access copied at creation")
        self.assertContains(response, "Run quality checks")
        self.assertContains(response, "data-confirm-submit")
        self.assertContains(response, 'id="account-confirm-dialog"')

    def test_settings_get_does_not_lazily_create_a_token(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("account_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            PersonalAccessToken.objects.filter(user=self.user).exists()
        )
        self.assertContains(response, "0 active tokens")
        self.assertContains(response, "Create token")
        self.assertContains(response, "Current password")
        self.assertNotContains(response, "qct_")

    def test_csrf_is_required_for_create_and_delete(self):
        token = issue_personal_access_token(self.user, "CSRF protected").token
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        create_response = self.post_create(client=csrf_client)
        delete_response = csrf_client.post(self.delete_url(token))

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(
            PersonalAccessToken.objects.filter(pk=token.pk).exists()
        )

    def test_valid_csrf_token_allows_creation(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_token = _get_new_csrf_string()
        csrf_client.cookies["csrftoken"] = csrf_token

        response = csrf_client.post(
            self.create_url,
            {
                "name": "CSRF-authorized",
                "current_password": self.password,
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            PersonalAccessToken.objects.filter(
                user=self.user,
                name="CSRF-authorized",
            ).exists()
        )
