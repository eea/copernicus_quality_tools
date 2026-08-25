"""Presentation and permission contracts for the deliveries workspace."""

import re
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase
from django.test import override_settings
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


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryWorkspacePresentationTests(TestCase):
    """Exercise semantic UX and permission-sensitive workspace controls."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delivery-workspace-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def workspace_sidebar(self, response):
        document = response.content.decode(response.charset)
        match = re.search(
            r'<aside\b[^>]*class="[^"]*\bworkspace-sidebar\b[^"]*"'
            r'[^>]*aria-label="Workspace navigation"[^>]*>(.*?)</aside>',
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(match, "The workspace needs a labelled sidebar.")
        return match.group(0)

    def permission(self, permission):
        return Permission.objects.get(
            content_type=capability_content_type(),
            codename=permission.value,
        )

    def remove_default_capabilities(self, *permissions):
        default_group = Group.objects.get(name=Role.DEFAULT.value)
        default_group.permissions.remove(
            *(self.permission(permission) for permission in permissions)
        )

    def test_sidebar_uses_only_real_routes_for_a_default_user(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "dashboard/includes/workspace_navigation.html",
        )
        sidebar = self.workspace_sidebar(response)
        self.assertEqual(sidebar.count('aria-current="page"'), 1)
        self.assertIn(
            'href="{}" aria-current="page"'.format(reverse("deliveries")),
            sidebar,
        )
        self.assertIn('href="{}"'.format(reverse("file_upload")), sidebar)
        self.assertIn(
            'href="https://eea.github.io/copernicus_quality_tools/"',
            sidebar,
        )
        self.assertNotIn('href="{}"'.format(reverse("boundaries")), sidebar)
        self.assertNotIn(
            'href="{}"'.format(reverse("announcement")),
            sidebar,
        )
        self.assertNotIn(
            'href="{}"'.format(reverse("admin:auth_user_changelist")),
            sidebar,
        )

        # The reference includes future destinations. Do not render dead
        # controls until those URL surfaces actually exist.
        for placeholder_label in (
            "Dashboard",
            "QC Results",
            "Reports",
            "Settings",
        ):
            self.assertNotIn(placeholder_label, sidebar)

        hrefs = re.findall(
            r'<a\b[^>]*\bhref="([^"]+)"',
            sidebar,
            flags=re.IGNORECASE,
        )
        self.assertTrue(hrefs)
        for href in hrefs:
            with self.subTest(href=href):
                self.assertNotEqual(href, "#")
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    self.assertEqual(parsed.scheme, "https")
                    continue
                try:
                    resolve(parsed.path)
                except Resolver404 as error:
                    self.fail(
                        "Workspace navigation points at an unknown route: "
                        "{} ({})".format(href, error)
                    )

        workspace_stylesheet = "dashboard/css/ui/workspace.css"
        self.assertIsNotNone(finders.find(workspace_stylesheet))
        self.assertEqual(
            response.content.decode(response.charset).count(
                static(workspace_stylesheet)
            ),
            1,
        )

    def test_sidebar_expands_only_for_effective_permissions(self):
        configuration_user = get_user_model().objects.create_user(
            username="workspace-configuration-user",
            password="test-password",
        )
        configuration_user.user_permissions.add(
            self.permission(AccountPermission.MANAGE_CONFIGURATION)
        )
        self.client.force_login(configuration_user)

        configuration_response = self.client.get(reverse("deliveries"))
        configuration_sidebar = self.workspace_sidebar(configuration_response)
        self.assertIn(
            'href="{}"'.format(reverse("boundaries")),
            configuration_sidebar,
        )
        self.assertIn(
            'href="{}"'.format(reverse("announcement")),
            configuration_sidebar,
        )
        self.assertNotIn(
            'href="{}"'.format(reverse("admin:auth_user_changelist")),
            configuration_sidebar,
        )

        administrator = get_user_model().objects.create_user(
            username="workspace-administrator",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

        administrator_response = self.client.get(reverse("deliveries"))
        administrator_sidebar = self.workspace_sidebar(administrator_response)
        self.assertIn(
            'href="{}"'.format(reverse("boundaries")),
            administrator_sidebar,
        )
        self.assertIn(
            'href="{}"'.format(reverse("announcement")),
            administrator_sidebar,
        )
        self.assertIn(
            'href="{}"'.format(reverse("admin:auth_user_changelist")),
            administrator_sidebar,
        )

    def test_upload_and_actions_follow_effective_permissions(self):
        permitted_response = self.client.get(reverse("deliveries"))

        self.assertContains(permitted_response, "Upload delivery")
        self.assertContains(permitted_response, "Open uploader")
        self.assertContains(permitted_response, 'id="btn-qc-multi"')
        self.assertContains(permitted_response, 'id="btn-delete-multi"')

        self.remove_default_capabilities(
            AccountPermission.UPLOAD_DELIVERY,
            AccountPermission.RUN_QC,
            AccountPermission.DELETE_DELIVERY,
            AccountPermission.SUBMIT_DELIVERY,
        )
        restricted_response = self.client.get(reverse("deliveries"))

        self.assertEqual(restricted_response.status_code, 200)
        self.assertNotContains(
            restricted_response,
            'href="{}"'.format(reverse("file_upload")),
        )
        self.assertNotContains(restricted_response, 'id="btn-qc-multi"')
        self.assertNotContains(restricted_response, 'id="btn-delete-multi"')
        self.assertNotContains(restricted_response, 'id="btn-submit-multi"')

    def test_summary_uses_semantic_term_and_value_pairs(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<dl class="deliveries-summary" '
            'aria-label="Delivery overview" '
            'aria-describedby="delivery-summary-scope">',
        )
        for label in ("Total deliveries", "Passed", "In progress", "Failed"):
            with self.subTest(label=label):
                self.assertContains(response, label)
        self.assertContains(response, "Boundary date")
        self.assertContains(
            response,
            "Overview of all active deliveries visible to you",
        )

        summary_response = self.client.get(reverse("deliveries_json"))
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(
            summary_response.json()["summary"],
            {
                "total": 0,
                "passed": 0,
                "in_progress": 0,
                "failed": 0,
                "not_checked": 0,
                "other": 0,
            },
        )

    def test_page_has_one_main_heading_and_an_accessible_table(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        self.assertEqual(document.count("<main"), 1)
        self.assertEqual(document.count("<h1"), 1)

        table = re.search(
            r'<table\b[^>]*\bid="tbl-deliveries"[^>]*>',
            document,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(table)
        table_end = document.find("</table>", table.end())
        self.assertNotEqual(table_end, -1)
        self.assertIn(
            '<caption class="sr-only">Uploaded delivery packages and their '
            "latest quality-control status</caption>",
            document[table.end() : table_end],
        )
        self.assertIn(
            'aria-describedby="deliveries-table-description"',
            table.group(0),
        )

        toolbar = re.search(
            r'<[^>]+\bid="runs-toolbar-1"[^>]*>',
            document,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(toolbar)
        toolbar_end = document.find(
            '<p id="deliveries-live-status"',
            toolbar.end(),
        )
        self.assertNotEqual(toolbar_end, -1)
        toolbar_markup = document[toolbar.start() : toolbar_end]
        self.assertIn(
            'role="group" aria-label="Selected delivery actions"',
            toolbar_markup,
        )
        self.assertIn(
            'aria-label="API credential controls"',
            toolbar_markup,
        )
