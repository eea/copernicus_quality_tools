import re

from django.contrib.auth import get_user_model
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_key,
)
from qc_tool.frontend.accounts.authentication.api_keys import digest_api_key
from qc_tool.frontend.accounts.authentication.api_keys import has_api_key
from qc_tool.frontend.accounts.models import ApiUser


class ApiCredentialViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="credential-owner",
            password="password",
        )
        self.rotate_url = reverse("api_credential_rotate")
        self.revoke_url = reverse("api_credential_revoke")

    def test_anonymous_user_is_redirected_before_credential_operation(self):
        response = self.client.post(self.rotate_url)

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={self.rotate_url}",
            fetch_redirect_response=False,
        )
        self.assertFalse(ApiUser.objects.filter(user=self.user).exists())

    def test_views_are_post_only_and_do_not_mutate_on_get(self):
        self.client.force_login(self.user)

        for url in (self.rotate_url, self.revoke_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 405)
        self.assertFalse(ApiUser.objects.filter(user=self.user).exists())

    def test_rotate_issues_one_time_secret_and_stores_only_digest(self):
        self.client.force_login(self.user)

        response = self.client.post(self.rotate_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "accounts/api_credentials/issued.html",
        )
        raw_key = response.context["api_key"]
        stored_value = ApiUser.objects.get(user=self.user).api_key
        self.assertRegex(raw_key, re.compile(r"qct_[A-Za-z0-9_-]{43}\Z"))
        self.assertRegex(stored_value, re.compile(r"sha256\$[0-9a-f]{64}\Z"))
        self.assertNotEqual(stored_value, raw_key)
        self.assertContains(response, raw_key)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            response["X-Robots-Tag"],
            "noindex, nofollow, noarchive",
        )
        self.assertNotIn(raw_key, self.client.session.values())

    def test_rotate_immediately_invalidates_previous_credential(self):
        self.client.force_login(self.user)
        first = self.client.post(self.rotate_url).context["api_key"]
        second = self.client.post(self.rotate_url).context["api_key"]

        self.assertNotEqual(first, second)
        self.assertIsNone(authenticate_api_key(first))
        self.assertEqual(authenticate_api_key(second), self.user)
        self.assertEqual(ApiUser.objects.filter(user=self.user).count(), 1)

    def test_revoke_deletes_credential_and_uses_fixed_redirect(self):
        self.client.force_login(self.user)
        raw_key = self.client.post(self.rotate_url).context["api_key"]

        response = self.client.post(
            self.revoke_url,
            {"next": "https://attacker.example/"},
        )

        self.assertRedirects(
            response,
            reverse("deliveries"),
            fetch_redirect_response=False,
        )
        self.assertFalse(has_api_key(self.user))
        self.assertIsNone(authenticate_api_key(raw_key))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_permission_is_checked_before_issue_or_revoke(self):
        self.client.force_login(self.user)
        # Bypass the protected-default-role signal to exercise the decorator's
        # fail-closed branch without login() saving and re-adding the role.
        self.user.groups.through.objects.filter(user_id=self.user.pk).delete()
        self.user.user_permissions.through.objects.filter(
            user_id=self.user.pk,
        ).delete()

        for url in (self.rotate_url, self.revoke_url):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 403)
        self.assertFalse(ApiUser.objects.filter(user=self.user).exists())

    def test_dashboard_get_does_not_lazily_create_or_expose_a_credential(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ApiUser.objects.filter(user=self.user).exists())
        self.assertContains(response, "Not configured")
        self.assertContains(response, ">Create</button>")
        self.assertNotContains(response, "qct_")

    def test_dashboard_shows_only_configured_status_for_existing_credential(self):
        raw_key = "qct_" + ("S" * 43)
        stored_digest = digest_api_key(raw_key)
        ApiUser.objects.create(user=self.user, api_key=stored_digest)
        self.client.force_login(self.user)

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configured")
        self.assertContains(response, ">Rotate</button>")
        self.assertContains(response, ">Revoke</button>")
        self.assertNotContains(response, raw_key)
        self.assertNotContains(response, stored_digest)
        self.assertEqual(
            ApiUser.objects.get(user=self.user).api_key,
            stored_digest,
        )

    def test_csrf_is_required_for_rotate_and_revoke(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        for url in (self.rotate_url, self.revoke_url):
            with self.subTest(url=url):
                response = csrf_client.post(url)
                self.assertEqual(response.status_code, 403)

    def test_valid_csrf_token_allows_rotation(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        csrf_token = _get_new_csrf_string()
        csrf_client.cookies["csrftoken"] = csrf_token

        response = csrf_client.post(
            self.rotate_url,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(has_api_key(self.user))
