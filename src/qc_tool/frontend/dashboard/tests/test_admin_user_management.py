"""User-management navigation reflects existing permissions without writes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.access.maintenance import is_maintenance_control_request
from qc_tool.frontend.dashboard.services import maintenance


@override_settings(MAINTENANCE_MODE=False)
class UserManagementAdminTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory(prefix="qc-user-management-")))
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
                                           QC_TOOL_TRANSFER_DIR=directory / "transfers"))
        User = get_user_model()
        self.administrator = User.objects.create_user(username="user-management-administrator")
        self.administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.manager = User.objects.create_user(username="user-management-manager")
        self.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.staff = User.objects.create_user(username="user-management-staff")
        User.objects.filter(pk=self.staff.pk).update(is_staff=True)
        self.staff.refresh_from_db()
        self.url = reverse("admin_user_management")
        self.client.force_login(self.administrator)

    def grant(self, codename, *, app_label="auth"):
        self.staff.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label=app_label))
        self.client.force_login(self.staff)

    def test_administrator_gets_existing_user_access_and_transfer_actions(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User management")
        expected = (
            reverse("admin:auth_user_add"), reverse("admin:auth_user_changelist"),
            reverse("admin:auth_group_changelist"), reverse("admin:accounts_userproductgrant_changelist"),
            reverse("admin_database_records", args=["auth_permission"]),
        )
        for url in expected:
            with self.subTest(url=url):
                self.assertContains(response, f'href="{url}"')
        self.assertTrue(response.context["can_transfer_users"])
        for tab, key in (("import", "users_import_url"), ("export", "users_export_url")):
            url = urlsplit(response.context[key])
            self.assertEqual(url.path, reverse("admin_data_transfer"))
            self.assertEqual(parse_qs(url.query), {"tab": [tab]})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_view_user_staff_sees_only_the_granted_user_list_action(self):
        self.grant("view_user")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["url"] for row in response.context["user_actions"]],
                         [reverse("admin:auth_user_changelist")])
        self.assertEqual(response.context["access_actions"], [])
        self.assertFalse(response.context["can_transfer_users"])
        self.assertNotContains(response, "Import users")
        self.assertNotContains(response, "Export users")
        self.assertNotContains(response, 'href="' + reverse("admin:auth_user_add") + '"')
        self.assertNotContains(response, 'href="' + reverse("admin_database_records", args=["auth_permission"]) + '"')

    def test_add_user_staff_gets_create_without_ungranted_management_links(self):
        self.grant("add_user")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["url"] for row in response.context["user_actions"]],
                         [reverse("admin:auth_user_add")])
        self.assertFalse(response.context["can_transfer_users"])
        self.assertEqual(response.context["access_actions"], [])

    def test_group_only_staff_gets_only_its_group_action(self):
        self.grant("view_group")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user_actions"], [])
        self.assertFalse(response.context["show_users_panel"])
        self.assertEqual([row["url"] for row in response.context["access_actions"]],
                         [reverse("admin:auth_group_changelist")])
        self.assertFalse(response.context["can_transfer_users"])

    def test_managers_and_ungranted_staff_cannot_open_user_management(self):
        for user in (self.manager, self.staff):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_child_model_permission_does_not_bypass_its_administrator_only_policy(self):
        self.grant("view_userproductgrant", app_label="accounts")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_reader_returns_to_admin_login(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, reverse("admin_login"))
        self.assertEqual(parse_qs(urlsplit(response.url).query)["next"], [self.url])

    def test_get_does_not_change_records_or_run_maintenance_probes(self):
        from unittest.mock import patch
        with patch.object(maintenance, "advance") as advance:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        advance.assert_not_called()
        self.assertEqual([item["sql"] for item in queries if item["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))], [])

    def test_post_is_not_a_user_mutation_endpoint(self):
        before = list(get_user_model().objects.values())
        self.assertFalse(is_maintenance_control_request(RequestFactory().post(self.url)))
        response = self.client.post(self.url, {"action": "delete", "username": self.administrator.username})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET")
        self.assertEqual(list(get_user_model().objects.values()), before)

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_maintenance_keeps_reading_and_transfers_but_disables_create_actions_without_writes(self):
        generation = maintenance.enable(self.administrator, expected_generation=0)["generation"]
        maintenance.advance(expected_generation=generation)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create user")
        self.assertNotContains(response, f'href="{reverse("admin:auth_user_add")}"')
        self.assertContains(response, f'href="{reverse("admin:auth_user_changelist")}"')
        self.assertContains(response, "Restore or import a package")
        self.assertContains(response, "Create backup")
        self.assertEqual([item["sql"] for item in queries if item["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))], [])
        self.assertEqual(self.client.post(self.url, {"action": "create"}).status_code, 503)
