"""Database pages keep a stable hierarchy and a clear return destination."""

from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from qc_tool.database.transfers import service
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services import maintenance


class _Navigation(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.ids = set()
        self._in_navigation = False
        self._link = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "nav" and attributes.get("aria-label") == "Database tasks":
            self._in_navigation = True
        if self._in_navigation and tag == "a":
            self._link = {**attributes, "text": ""}

    def handle_data(self, data):
        if self._link is not None:
            self._link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self._link["text"] = self._link.get("aria-label") or " ".join(self._link["text"].split())
            self.links.append(self._link)
            self._link = None
        if tag == "nav":
            self._in_navigation = False


@override_settings(MAINTENANCE_MODE=False)
class AdminDatabaseNavigationTests(TestCase):
    operation_id = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da"

    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
        ))
        actor = get_user_model().objects.create_user(username="database-navigation-admin")
        actor.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(actor)
        self.url = reverse("admin_data_transfer")
        self.enterContext(patch.object(service, "schema_readiness", return_value={
            "ready": True, "message": "Schema matches.",
        }))
        self.enterContext(patch.object(service, "database_availability", return_value={
            "ready": False, "message": "Native tools unavailable.",
            "can_create_restore_database": False,
        }))
        self.control_state = {
            "active_database": "qc_live", "previous_database": "", "revision": 0,
        }
        self.enterContext(patch.object(service, "database_control_status", return_value=self.control_state))
        self.operations = self.enterContext(patch.object(service, "list_operations", return_value=[]))
        self.enterContext(patch.object(service, "backup_storage_capacity", return_value={
            "free_bytes": 4096, "reserve_bytes": 1024,
        }))
        self.enterContext(patch.object(service, "database_inventory", return_value={
            "supported": True, "available": True, "active_database": "qc_live", "databases": [],
        }))

    def assert_section(self, response, current):
        self.assertEqual(response.status_code, 200)
        navigation = _Navigation(response.content.decode())
        self.assertEqual([item["text"] for item in navigation.links],
                         ["Database status", "Back up & restore", "Manage databases", "Progress & history"])
        self.assertEqual([(item["text"], item["href"]) for item in navigation.links
                          if item.get("aria-current") == "page"], [(current, {
                              "Database status": self.url,
                              "Manage databases": self.url + "?tab=databases",
                              "Back up & restore": self.url + "?tab=backups",
                              "Progress & history": self.url + "?tab=activity",
                          }[current])])
        for link in navigation.links:
            self.assertEqual(link.get("aria-label"), link["text"])
            self.assertTrue(link.get("aria-describedby"), "Each task explains what it opens")
            self.assertTrue(set(link["aria-describedby"].split()).issubset(navigation.ids))

    def test_overview_and_section_pages_share_the_same_navigation(self):
        for query, current in (({}, "Database status"), ({"tab": "databases"}, "Manage databases"),
                               ({"tab": "backups"}, "Back up & restore"), ({"tab": "activity"}, "Progress & history")):
            with self.subTest(current=current):
                self.assert_section(self.client.get(self.url, query), current)

    def test_section_titles_and_overview_return_links_match_the_navigation(self):
        response = self.client.get(self.url)
        self.assertContains(response, "<h1>Database status</h1>", html=True)
        for tab, title in (("databases", "Manage databases"), ("backups", "Back up & restore"), ("activity", "Progress & history")):
            with self.subTest(tab=tab):
                response = self.client.get(self.url, {"tab": tab})
                self.assertContains(response, "<h1>" + escape(title) + "</h1>", html=True)
                self.assertContains(response, "Back to Database status")

    def test_existing_history_bookmarks_open_backups_and_preserve_the_saved_files_anchor(self):
        for alias in ("history", "transfers"):
            with self.subTest(alias=alias):
                response = self.client.get(self.url, {"tab": alias})
                self.assert_section(response, "Back up & restore")
                self.assertContains(response, 'id="backup-files"')
                self.assertContains(response, "<h1>Back up &amp; restore</h1>", html=True)
                self.assertNotContains(response, 'id="transfer-history"')
                html = response.content.decode()
                self.assertLess(html.index('id="backup-files"'), html.index("<h1>Back up &amp; restore</h1>"))

    def test_backup_tasks_stay_under_backups_with_an_explicit_return_link(self):
        for tab in ("export", "import"):
            with self.subTest(tab=tab):
                response = self.client.get(self.url, {"tab": tab})
                self.assert_section(response, "Back up & restore")
                self.assertContains(response, 'href="' + self.url + '?tab=backups"')
                self.assertContains(response, "Back to Back up &amp; restore")
                self.assertNotContains(response, 'id="backup-files"')

    def test_activity_is_distinct_from_saved_backup_files(self):
        response = self.client.get(self.url, {"tab": "activity"})
        self.assert_section(response, "Progress & history")
        self.assertContains(response, "<h1>Progress &amp; history</h1>", html=True)
        self.assertContains(response, 'id="transfer-history"')
        self.assertNotContains(response, 'id="backup-files"')

    def test_operation_details_return_to_the_section_that_opened_them(self):
        operation = {
            "id": self.operation_id, "kind": "export", "profile": "database",
            "status": "completed", "downloadable": True, "package_bytes": 2048,
        }
        with patch.object(service, "get_operation", return_value=operation):
            for origin, section, label in ((None, "Back up & restore", "Back to Back up &amp; restore"),
                                           ("backups", "Back up & restore", "Back to Back up &amp; restore"),
                                           ("unknown", "Back up & restore", "Back to Back up &amp; restore"),
                                           ("https://external.example/", "Back up & restore", "Back to Back up &amp; restore"),
                                           ("databases", "Manage databases", "Back to Manage databases"),
                                           ("activity", "Progress & history", "Back to Progress &amp; history")):
                with self.subTest(origin=origin):
                    query = {"operation": self.operation_id}
                    if origin:
                        query["from"] = origin
                    response = self.client.get(self.url, query)
                    self.assert_section(response, section)
                    self.assertContains(response, "<h1>Backup ready to download</h1>", html=True)
                    self.assertContains(response, label)
                    self.assertContains(response, reverse("admin_data_transfer_download", args=[self.operation_id]))

    def test_activity_links_preserve_the_return_destination(self):
        self.operations.return_value = [{
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "completed",
        }]
        response = self.client.get(self.url, {"tab": "activity"})
        self.assertContains(response, "Manage databases")
        self.assertContains(response, "from=activity")
        response = self.client.get(self.url, {"tab": "backups"})
        self.assertNotContains(response, "from=activity")

    def test_refresh_and_maintenance_keep_the_activity_return_destination(self):
        operation = {
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "running",
            "downloadable": False, "runner_active": True, "recoverable": False, "cancellable": False,
        }
        with patch.object(service, "get_operation", return_value=operation):
            response = self.client.get(self.url, {"operation": self.operation_id, "from": "activity"})
        self.assert_section(response, "Progress & history")
        self.assertContains(response, "<h1>Creating your backup</h1>", html=True)
        refresh_query = parse_qs(urlsplit(response.context["operation_refresh_url"]).query)
        self.assertEqual(refresh_query["from"], ["activity"])
        maintenance_query = parse_qs(urlsplit(response.context["maintenance_url"]).query)
        return_query = parse_qs(urlsplit(maintenance_query["next"][0]).query)
        self.assertEqual(return_query["from"], ["activity"])
        self.assertEqual(return_query["operation"], [self.operation_id])

    def test_database_manager_origin_survives_refresh_maintenance_and_child_actions(self):
        operation = {
            "id": self.operation_id, "kind": "import", "profile": "database", "status": "completed",
            "result": {"verified": True, "target_database": "qc_restored"},
        }
        with patch.object(service, "get_operation", return_value=operation):
            response = self.client.get(self.url, {"operation": self.operation_id, "from": "databases"})
        self.assert_section(response, "Manage databases")
        self.assertEqual(response.context["database_back_url"], self.url + "?tab=databases")
        self.assertEqual(response.context["database_breadcrumbs"][-2], {
            "label": "Manage databases", "url": self.url + "?tab=databases",
        })
        for key in ("operation_refresh_url", "transfer_action_url"):
            destination = urlsplit(response.context[key])
            self.assertEqual(destination.path, self.url)
            self.assertEqual(parse_qs(destination.query)["from"], ["databases"])
        maintenance_query = parse_qs(urlsplit(response.context["maintenance_url"]).query)
        return_query = parse_qs(urlsplit(maintenance_query["next"][0]).query)
        self.assertEqual(return_query["from"], ["databases"])
        self.assertEqual(return_query["operation"], [self.operation_id])

    def test_database_manager_origin_keeps_transfer_review_on_the_transfer_handler(self):
        actor = get_user_model().objects.get(username="database-navigation-admin")
        enabled = maintenance.enable(actor, expected_generation=0)
        maintenance.advance(expected_generation=enabled["generation"])
        operation = {
            "id": self.operation_id, "kind": "import", "profile": "database", "status": "completed",
            "result": {"verified": True, "target_database": "qc_restored"},
        }
        preview = {
            "can_apply": True, "blockers": [], "review_hash": "e" * 64,
            "target_database": "qc_restored", "source_database": "qc_live",
            "revision": 0, "requires_credentials": False,
        }
        payload = {"action": "review_database_switch", "operation_id": self.operation_id}
        with (patch.object(service, "get_operation", return_value=operation),
              patch.object(service, "activation_preview", return_value=preview) as review,
              patch.object(service, "activate_database") as activate,
              patch.object(service, "select_database") as select):
            response = self.client.post(self.url + "?from=databases", payload)
            self.assert_section(response, "Manage databases")
            self.assertContains(response, "<h1>Review database switch</h1>", html=True)
            self.assertContains(response, "Back to Manage databases")
            # Follow the rendered form destination: tab=databases must not send
            # an operation action to the unrelated database-inventory handler.
            response = self.client.post(response.context["transfer_action_url"], payload)
        self.assert_section(response, "Manage databases")
        self.assertContains(response, "<h1>Review database switch</h1>", html=True)
        self.assertEqual(review.call_count, 2)
        activate.assert_not_called()
        select.assert_not_called()

    def test_switch_review_form_posts_back_to_its_activity_origin(self):
        actor = get_user_model().objects.get(username="database-navigation-admin")
        enabled = maintenance.enable(actor, expected_generation=0)
        maintenance.advance(expected_generation=enabled["generation"])
        operation = {
            "id": self.operation_id, "kind": "import", "profile": "database", "status": "completed",
            "result": {"verified": True, "target_database": "qc_restored"},
        }
        with (patch.object(service, "get_operation", return_value=operation),
              patch.object(service, "activation_preview", return_value={
                  "can_apply": True, "blockers": [], "review_hash": "e" * 64,
                  "target_database": "qc_restored", "source_database": "qc_live",
                  "revision": 0, "requires_credentials": False,
              }), patch.object(service, "activate_database") as activate):
            response = self.client.post(self.url + "?from=activity", {
                "action": "review_database_switch", "operation_id": self.operation_id,
            })
        self.assert_section(response, "Progress & history")
        self.assertContains(response, 'action="' + self.url + '?tab=activity&amp;from=activity"')
        self.assertContains(response, "Back to Progress &amp; history")
        activate.assert_not_called()

    def test_switch_back_form_keeps_activity_after_a_post_without_an_operation(self):
        actor = get_user_model().objects.get(username="database-navigation-admin")
        enabled = maintenance.enable(actor, expected_generation=0)
        maintenance.advance(expected_generation=enabled["generation"])
        generation = maintenance.read_status()["generation"]
        self.control_state.update(previous_database="qc_previous", revision=4, has_selection=True)
        response = self.client.get(self.url, {"tab": "activity"})
        self.assertContains(response, 'action="' + self.url + '?tab=activity&amp;from=activity"')
        with patch.object(service, "rollback_database") as rollback:
            response = self.client.post(self.url + "?tab=activity&from=activity", {
                "action": "rollback_database", "rollback-generation": generation, "rollback-revision": 4,
                "rollback-destination_confirmation": "qc_previous", "rollback-confirmed_storage": "on",
            })
        self.assert_section(response, "Progress & history")
        self.assertContains(response, "Switched back to the previous database")
        self.assertNotContains(response, 'name="operation_id"')
        rollback.assert_called_once()

    def test_navigation_never_starts_a_transfer_or_changes_the_database(self):
        actions = ("create_export", "stage_import", "start_import", "release_export_package",
                   "select_database", "delete_restore_database")
        mocks = [self.enterContext(patch.object(service, action)) for action in actions]
        for tab in ("backups", "activity", "history", "export", "import", "databases"):
            response = self.client.get(self.url, {"tab": tab, "action": "delete_database"})
            self.assertEqual(response.status_code, 200)
        for action in mocks:
            action.assert_not_called()

