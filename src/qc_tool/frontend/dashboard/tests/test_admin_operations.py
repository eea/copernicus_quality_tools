"""Administration sections share one deliberate workspace return control."""

from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.urls import get_script_prefix, set_script_prefix

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services import maintenance


class _AdminMarkup(HTMLParser):
    """Inspect landmarks without depending on attribute order or presentation."""

    def __init__(self, response):
        super().__init__()
        self.elements = []
        self.feed(response.content.decode())

    def matching(self, tag, **attributes):
        return [
            element for element_tag, element in self.elements
            if element_tag == tag
            and all(element.get(key) == value for key, value in attributes.items())
        ]

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


@override_settings(MAINTENANCE_MODE=False)
class AdminOperationsTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=Path(directory) / "maintenance",
            QC_TOOL_TRANSFER_DIR=Path(directory) / "transfers",
        ))
        self.administrator = get_user_model().objects.create_user(
            username="operations-administrator",
        )
        self.administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(self.administrator)

    def assert_admin_links(self, response):
        """Only the explicit return link leaves Admin for the workspace."""
        admin_root = reverse("admin:index")
        static_root = urlsplit(settings.STATIC_URL).path
        workspace_links = []
        for element in _AdminMarkup(response).matching("a"):
            href = element.get("href", "")
            parsed = urlsplit(href)
            with self.subTest(href=href):
                if "qc-admin-workspace-link" in element.get("class", "").split():
                    self.assertEqual(href, reverse("dashboard_home"))
                    workspace_links.append(element)
                    continue
                if parsed.scheme or parsed.netloc:
                    self.assertEqual(parsed.scheme, "https")
                    self.assertEqual(parsed.netloc, "eea.github.io")
                    self.assertTrue(parsed.path.startswith("/copernicus_quality_tools/"))
                elif parsed.path:
                    self.assertTrue(
                        parsed.path.startswith(admin_root)
                        or bool(static_root and parsed.path.startswith(static_root)),
                        f"Administration links outside its own interface: {href}",
                    )
        self.assertEqual(len(workspace_links), 1)
        for route in (
            "products", "product_upload", "boundaries",
            "announcement", "deliveries", "submission_queue",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, "Open workspace")

    def test_administrator_finds_user_database_and_storage_sections(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administration")
        for route in (
            "admin_user_management", "admin_maintenance", "admin_data_transfer", "admin_storage",
        ):
            self.assertContains(response, f'href="{reverse(route)}"')
        self.assert_admin_links(response)

    def test_home_has_three_primary_panels_without_workspace_or_model_directory(self):
        response = self.client.get(reverse("admin:index"))
        markup = _AdminMarkup(response)

        self.assertEqual(len(markup.matching("h1")), 1)
        self.assertEqual(len(markup.matching("h2")), 3)
        for panel in ("qc-admin-users", "qc-admin-database", "qc-admin-storage"):
            self.assertEqual(len(markup.matching("section", id=panel)), 1)
        self.assertContains(response, "User management")
        self.assertContains(response, "Database")
        self.assertContains(response, "Storage")
        self.assertContains(response, "Open user management")
        for route in ("admin:auth_user_add", "admin:auth_user_changelist"):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        for identifier in (
            "qc-admin-model-directory", "qc-admin-start-here", "workspace-heading",
        ):
            self.assertNotContains(response, f'id="{identifier}"')
        for route in (
            "admin:dashboard_job_changelist",
            "admin:dashboard_deliverysubmission_changelist",
            "admin:dashboard_submissionconflict_changelist",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, "Advanced administration")
        self.assertNotContains(response, 'id="recent-actions-module"')

    def test_admin_pages_share_the_four_administration_sections(self):
        for route in (
            "admin:index", "admin:auth_user_changelist",
            "admin:auth_group_changelist", "admin_user_management",
            "admin_data_transfer", "admin_maintenance", "admin_storage",
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "CLMS QC Tool")
                for destination in (
                    "admin:index", "admin_user_management", "admin_data_transfer", "admin_storage",
                ):
                    self.assertContains(
                        response, f'href="{reverse(destination)}"',
                    )
                self.assert_admin_links(response)

    def test_admin_navigation_respects_a_deployment_path_prefix(self):
        previous_prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, previous_prefix)
        set_script_prefix("/quality/")

        response = self.client.get("/admin/", SCRIPT_NAME="/quality")

        self.assertEqual(response.status_code, 200)
        for route in (
            "admin:index", "admin_user_management", "admin_data_transfer", "admin_storage",
        ):
            self.assertContains(response, f'href="{reverse(route)}"')
            self.assertTrue(reverse(route).startswith("/quality/"))
        self.assert_admin_links(response)

    def test_maintenance_card_distinguishes_readiness_from_stopping(self):
        current = maintenance.read_status()
        for enabled, phase, label in (
            (False, "off", "Maintenance is off"),
            (True, "stopping", "Turning on maintenance"),
            (True, "ready", "Maintenance is on"),
            (True, "unavailable", "Status unavailable"),
        ):
            with self.subTest(phase=phase), patch(
                "qc_tool.frontend.dashboard.middleware.read_status",
                return_value={**current, "enabled": enabled, "phase": phase},
            ):
                response = self.client.get(reverse("admin:index"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, label)
                self.assertContains(
                    response, f'href="{reverse("admin_maintenance")}"',
                )
                self.assert_admin_links(response)

    def test_qc_administrator_can_read_global_job_history_without_editing(self):
        self.assertFalse(self.administrator.is_superuser)
        self.assertFalse(self.administrator.has_perm("dashboard.view_job"))

        response = self.client.get(reverse("admin:dashboard_job_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response, f'href="{reverse("admin:dashboard_job_add")}"',
        )
        self.assertEqual(
            self.client.get(reverse("admin:dashboard_job_add")).status_code, 403,
        )

    def test_product_manager_has_only_the_explicit_workspace_return_link(self):
        manager = get_user_model().objects.create_user(username="operations-manager")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(manager)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="qc-admin-users"')
        self.assertNotContains(response, 'id="qc-admin-database"')
        self.assertNotContains(response, 'id="qc-admin-storage"')
        self.assert_admin_links(response)
        for route in (
            "admin_maintenance", "admin_data_transfer",
            "admin_user_management", "admin_storage",
            "admin:auth_user_changelist", "admin:auth_group_changelist",
            "admin:dashboard_job_changelist",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_staff_flag_alone_does_not_expose_operational_links(self):
        staff = get_user_model().objects.create_user(username="operations-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        self.client.force_login(staff)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="qc-admin-users"')
        self.assertNotContains(response, 'id="qc-admin-database"')
        self.assertNotContains(response, 'id="qc-admin-storage"')
        self.assertNotContains(response, 'id="qc-admin-model-directory"')
        for route in (
            "admin_maintenance", "admin_data_transfer", "admin_user_management", "admin_storage", "submission_queue",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assert_admin_links(response)
        self.assertEqual(
            self.client.get(reverse("admin:dashboard_job_changelist")).status_code,
            403,
        )

    def test_staff_only_sees_the_account_actions_they_are_granted(self):
        staff = get_user_model().objects.create_user(username="account-read-only-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.user_permissions.add(Permission.objects.get(
            content_type__app_label="auth", codename="view_user",
        ))
        staff.refresh_from_db()
        self.client.force_login(staff)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("admin_user_management")}"')
        child = self.client.get(reverse("admin_user_management"))
        self.assertContains(child, f'href="{reverse("admin:auth_user_changelist")}"')
        for route in (
            "admin:auth_user_add", "admin:auth_group_changelist",
            "admin_data_transfer", "admin_maintenance", "admin_storage",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, 'id="qc-admin-database"')
        self.assert_admin_links(response)

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_maintenance_keeps_navigation_read_only_and_blocks_job_mutation(self):
        maintenance.enable(self.administrator, expected_generation=0)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("admin:index"))
            jobs = self.client.get(reverse("admin:dashboard_job_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(jobs.status_code, 200)
        self.assertContains(response, "Turning on maintenance. QC work is stopping.")
        self.assert_admin_links(response)
        self.assertEqual([
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(
                ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "),
            )
        ], [])
        self.assertEqual(
            self.client.post(reverse("admin:dashboard_job_changelist"), {
                "action": "delete_selected", "_selected_action": "1",
            }).status_code,
            503,
        )
