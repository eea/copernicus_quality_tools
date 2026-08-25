from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase
from django.test import TestCase
from django.urls import NoReverseMatch
from django.urls import Resolver404
from django.urls import resolve
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


class ConfigurationNavigationTests(TestCase):
    def create_user(self, username):
        return get_user_model().objects.create_user(
            username=username,
            password="test-password",
        )

    def grant_configuration_permission(self, user):
        permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        )
        user.user_permissions.add(permission)

    def test_direct_permission_allows_configuration_pages_and_navigation(self):
        user = self.create_user("configuration-editor")
        self.grant_configuration_permission(user)
        self.client.force_login(user)

        response = self.client.get(reverse("boundaries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("announcement")}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("boundaries")}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("admin:auth_user_changelist")}"',
        )

    def test_admin_role_sees_django_admin_navigation(self):
        user = self.create_user("application-administrator")
        user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(user)

        response = self.client.get(reverse("boundaries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("admin:auth_user_changelist")}"',
        )

    def test_authenticated_forbidden_page_uses_friendly_html_response(self):
        user = self.create_user("default-only-user")
        self.client.force_login(user)

        response = self.client.get(reverse("boundaries"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "accounts/errors/403.html")
        self.assertContains(
            response,
            "You do not have access to this page",
            status_code=403,
        )
        self.assertNotContains(
            response,
            AccountPermission.MANAGE_CONFIGURATION.value,
            status_code=403,
        )


class AuthenticationUrlTests(SimpleTestCase):
    def test_only_supported_django_auth_routes_are_exposed(self):
        self.assertEqual(reverse("login"), "/accounts/login/")
        self.assertEqual(reverse("logout"), "/accounts/logout/")
        self.assertEqual(
            reverse("password_change"),
            "/accounts/password_change/",
        )

        with self.assertRaises(NoReverseMatch):
            reverse("password_reset")
        with self.assertRaises(Resolver404):
            resolve("/accounts/password_reset/")


class ApiAuthenticationResponseTests(SimpleTestCase):
    def test_missing_api_key_returns_authentication_challenge(self):
        response = self.client.get(reverse("api_product_list"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer realm="QC Tool API"',
        )
        self.assertEqual(response.json()["status"], "error")
