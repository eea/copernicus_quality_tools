"""The account/database overview preserves operational boundaries."""

from contextlib import ExitStack
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.database.transfers import service as transfers
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services import maintenance


class _OverviewLinks(HTMLParser):
    VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, response):
        super().__init__()
        self.links = []
        self.elements = []
        self.text = {}
        self.ancestors = {}
        self._stack = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        self.elements.append((tag, attributes))
        identifier = attributes.get("id")
        if identifier:
            self.text[identifier] = []
            self.ancestors[identifier] = [
                parent.get("id") for _tag, parent in self._stack if parent.get("id")
            ]
        if tag == "a" and "href" in attributes:
            self.links.append(attributes["href"])
        if tag not in self.VOID_ELEMENTS:
            self._stack.append((tag, attributes))

    def handle_data(self, data):
        for _tag, attributes in self._stack:
            if attributes.get("id") in self.text:
                self.text[attributes["id"]].append(data)

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def text_for(self, identifier):
        return " ".join("".join(self.text.get(identifier, [])).split())

    def transfer_destinations(self):
        endpoint = reverse("admin_data_transfer")
        return [
            parse_qs(urlsplit(link).query)
            for link in self.links
            if urlsplit(link).path == endpoint
        ]

    def matching(self, tag, **attributes):
        return [
            element for element_tag, element in self.elements
            if element_tag == tag
            and all(element.get(key) == value for key, value in attributes.items())
        ]


@override_settings(MAINTENANCE_MODE=False)
class AdminOverviewTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
        ))
        self.administrator = get_user_model().objects.create_user(
            username="overview-administrator",
        )
        self.administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(self.administrator)

    def test_overview_links_to_user_management_database_storage_and_history(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        links = _OverviewLinks(response)
        endpoint = reverse("admin_data_transfer")
        self.assertIn(endpoint, links.links)
        self.assertIn(reverse("admin_user_management"), links.links)
        self.assertIn(reverse("admin_storage"), links.links)
        self.assertIn(f"{endpoint}?tables=1#database-records-heading", links.links)
        self.assertIn(f"{endpoint}#database-maintenance-heading", links.links)
        self.assertIn({"section": ["records"], "tab": ["import"]}, links.transfer_destinations())
        self.assertIn({"tab": ["history"]}, links.transfer_destinations())
        self.assertNotContains(response, "Restore database")

    def test_maintenance_status_uses_plain_language_and_one_settings_destination(self):
        for phase, title, action in (
            ("off", "Maintenance is off", "Maintenance settings"),
            ("stopping", "Turning on maintenance", "View maintenance progress"),
            ("ready", "Maintenance is on", "Maintenance settings"),
        ):
            with self.subTest(phase=phase):
                state = {
                    **maintenance.read_status(),
                    "enabled": phase != "off",
                    "phase": phase,
                }
                with (
                    patch("qc_tool.frontend.dashboard.middleware.read_status", return_value=state),
                    patch.object(maintenance, "advance") as advance,
                ):
                    response = self.client.get(reverse("admin:index"))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(_OverviewLinks(response).text_for("service-heading"), title)
                self.assertContains(
                    response, f'href="{reverse("admin_maintenance")}"',
                )
                self.assertContains(response, action)
                self.assertNotContains(response, "Check workers")
                self.assertNotContains(response, "worker readiness")
                advance.assert_not_called()

    def test_product_manager_does_not_receive_database_task_shortcuts(self):
        manager = get_user_model().objects.create_user(username="overview-manager")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(manager)

        with patch(
            "qc_tool.frontend.dashboard.services.admin_overview.active_operation",
        ) as active_operation:
            response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_OverviewLinks(response).transfer_destinations(), [])
        for route in (
            "submission_queue", "products", "deliveries",
        ):
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, 'id="qc-admin-start-here"')
        self.assertNotContains(response, 'id="qc-admin-service-status"')
        active_operation.assert_not_called()

    def test_record_pages_do_not_read_home_transfer_summary(self):
        with patch(
            "qc_tool.frontend.dashboard.services.admin_overview.active_operation",
        ) as active_operation:
            response = self.client.get(reverse("admin:dashboard_job_changelist"))

        self.assertEqual(response.status_code, 200)
        active_operation.assert_not_called()

    def test_overview_does_not_probe_database_schema_or_backup_tools(self):
        with (
            patch.object(transfers, "schema_readiness") as schema_readiness,
            patch.object(transfers, "database_availability") as database_availability,
        ):
            response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        schema_readiness.assert_not_called()
        database_availability.assert_not_called()

    def test_user_database_and_storage_panels_keep_maintenance_with_database_tasks(self):
        response = self.client.get(reverse("admin:index"))
        markup = _OverviewLinks(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(markup.matching("section", id="qc-admin-users")), 1)
        self.assertEqual(len(markup.matching("section", id="qc-admin-database")), 1)
        self.assertEqual(len(markup.matching("section", id="qc-admin-storage")), 1)
        for route in (
            "admin_user_management", "admin:auth_group_changelist", "admin_storage",
        ):
            with self.subTest(route=route):
                self.assertIn(reverse(route), markup.links)
        self.assertNotIn(reverse("admin:auth_user_add"), markup.links)
        self.assertNotIn(reverse("admin:auth_user_changelist"), markup.links)
        self.assertIn("qc-admin-database", markup.ancestors.get("qc-admin-service-status", []))
        self.assertNotContains(response, 'id="qc-admin-start-here"')
        self.assertNotContains(response, "First time administering QC Tool?")

    def test_pinned_transfer_links_to_its_review_instead_of_suggesting_resume(self):
        operation_id = "fcd4e1bf-093e-47bf-99cf-80090ab7e8e3"
        state = {**maintenance.read_status(), "enabled": True, "phase": "ready"}
        with (
            patch("qc_tool.frontend.dashboard.middleware.read_status", return_value=state),
            patch(
                "qc_tool.frontend.dashboard.services.admin_overview.active_operation",
                return_value={"operation_id": operation_id, "kind": "import", "generation": 1},
            ),
        ):
            response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        destinations = _OverviewLinks(response).transfer_destinations()
        self.assertTrue(any(
            destination.get("operation") == [operation_id]
            for destination in destinations
        ))
        self.assertContains(response, "View current transfer")
        self.assertNotContains(response, "Resume normal operation")

    def test_unreadable_transfer_pin_never_claims_maintenance_readiness(self):
        state = {**maintenance.read_status(), "enabled": True, "phase": "ready"}
        with (
            patch("qc_tool.frontend.dashboard.middleware.read_status", return_value=state),
            patch(
                "qc_tool.frontend.dashboard.services.admin_overview.active_operation",
                side_effect=maintenance.MaintenanceError("The transfer pin cannot be read."),
            ),
        ):
            response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Status unavailable")
        self.assertNotEqual(_OverviewLinks(response).text_for("service-heading"), "Maintenance is on")
        self.assertNotContains(response, "Normal operation")

    def test_unknown_maintenance_phase_never_claims_normal_operation(self):
        state = {**maintenance.read_status(), "enabled": False, "phase": "unknown"}
        with patch(
            "qc_tool.frontend.dashboard.middleware.read_status", return_value=state,
        ):
            response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Status unavailable")
        self.assertNotContains(response, "Maintenance is off")
        self.assertNotContains(response, "Normal operation")

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_viewing_ready_overview_never_starts_operational_work(self):
        state = {**maintenance.read_status(), "enabled": True, "phase": "ready"}
        with ExitStack() as stack:
            stack.enter_context(patch(
                "qc_tool.frontend.dashboard.middleware.read_status",
                return_value=state,
            ))
            operations = [
                stack.enter_context(patch.object(owner, name))
                for owner, names in (
                    (maintenance, ("enable", "disable", "advance", "retire_worker")),
                    (transfers, (
                        "create_export", "stage_import", "start_import",
                        "prepare_restore_destination", "activate_database",
                        "rollback_database", "recover_operation",
                    )),
                )
                for name in names
            ]
            queries = stack.enter_context(CaptureQueriesContext(connection))
            response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-QC-Maintenance"], "on")
        for operation in operations:
            operation.assert_not_called()
        mutations = [
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(
                ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "),
            )
        ]
        self.assertEqual(mutations, [])
