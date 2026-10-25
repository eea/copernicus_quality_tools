from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_direct_permission_allows_configuration_workspace_navigation(self):
        user = self.create_user("configuration-editor")
        self.grant_configuration_permission(user)
        self.client.force_login(user)

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("announcement")}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("boundaries")}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("admin:index")}"',
        )

    def test_admin_role_sees_django_admin_workspace_navigation(self):
        user = self.create_user("application-administrator")
        user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(user)

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("admin:index")}"',
        )

    def test_authenticated_forbidden_page_uses_friendly_html_response(self):
        user = self.create_user("default-only-user")
        self.client.force_login(user)

        response = self.client.get(reverse("product_upload"))

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

    def test_boundary_pages_and_data_are_only_available_to_administrators(self):
        user = self.create_user("boundary-viewer")
        configuration_editor = self.create_user("boundary-configuration-editor")
        self.grant_configuration_permission(configuration_editor)
        manager = self.create_user("boundary-product-manager")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        staff = self.create_user("boundary-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()

        for principal in (user, configuration_editor, manager, staff):
            self.client.force_login(principal)
            for route_name in ("boundaries", "boundaries_upload"):
                with self.subTest(user=principal.username, route=route_name):
                    response = self.client.get(reverse(route_name))
                    self.assertEqual(response.status_code, 403)
                    self.assertTemplateUsed(response, "admin/qc_tool_error.html")
                    self.assertContains(response, "Return to administration", status_code=403)
                    self.assertContains(
                        response, f'href="{reverse("dashboard_home")}"', count=1, status_code=403,
                    )
                    self.assertContains(response, "qc-admin-workspace-link", count=1, status_code=403)
                    self.assertNotContains(response, "Go to homepage", status_code=403)
            for route_name, args, method in (
                ("boundaries_json", ("raster",), "get"),
                ("boundaries_upload_data", (), "post"),
                ("boundaries_export", (), "post"),
            ):
                with self.subTest(user=principal.username, route=route_name):
                    response = getattr(self.client, method)(reverse(route_name, args=args))
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json()["code"], "permission_denied")

    def test_administrator_can_review_the_current_boundary_catalog(self):
        user = self.create_user("boundary-administrator")
        user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(user)
        page_response = self.client.get(reverse("boundaries"))
        self.assertEqual(page_response.status_code, 200)
        self.assertTemplateUsed(page_response, "admin/boundaries/index.html")
        self.assertContains(page_response, f'href="{reverse("boundaries_upload")}"')
        self.assertContains(page_response, "Replace boundary package")

        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster_dir = root / "raster"
            vector_dir = root / "vector"
            raster_dir.mkdir()
            vector_dir.mkdir()
            (raster_dir / "reviewable.tif").write_bytes(b"boundary")
            generation = SimpleNamespace(
                raster_dir=raster_dir,
                vector_dir=vector_dir,
            )
            with patch(
                "qc_tool.frontend.dashboard.views.boundaries."
                "resolve_boundary_generation",
                return_value=generation,
            ):
                list_response = self.client.get(
                    reverse("boundaries_json", args=("raster",))
                )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            list_response.json(),
            [
                {
                    "filename": "reviewable.tif",
                    "size_bytes": 8,
                    "type": "raster",
                }
            ],
        )

    def test_administrator_can_open_boundary_replacement_inside_admin(self):
        user = self.create_user("boundary-editor")
        user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(user)

        page_response = self.client.get(reverse("boundaries"))
        upload_response = self.client.get(reverse("boundaries_upload"))

        self.assertEqual(page_response.status_code, 200)
        self.assertContains(
            page_response,
            f'href="{reverse("boundaries_upload")}"',
        )
        self.assertContains(page_response, "Replace boundary package")
        self.assertContains(
            page_response,
            "Replace the boundary package to add them.",
        )
        self.assertEqual(upload_response.status_code, 200)
        self.assertTemplateUsed(
            upload_response,
            "admin/base_site.html",
        )
        self.assertTemplateNotUsed(upload_response, "dashboard/layouts/workspace.html")
        self.assertContains(upload_response, f'href="{reverse("boundaries")}"')


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
