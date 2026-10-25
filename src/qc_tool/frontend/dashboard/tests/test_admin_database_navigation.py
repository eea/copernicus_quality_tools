"""Database pages keep a stable hierarchy and a clear return destination."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.database.transfers import service
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services import maintenance


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

    def assert_workspace(self, response, workflow):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["transfer_task"], workflow)
        self.assertNotContains(response, 'aria-label="Maintenance tasks"')
        label = "Create backup" if workflow == "export" else "Restore from ZIP"
        self.assertEqual(response.context["database_breadcrumbs"][1]["label"], label)
        expected_back = (reverse("admin_backup_" + workflow) if response.context["operation"]
                         else reverse("admin_maintenance"))
        self.assertEqual(response.context["database_back_url"], expected_back)
        self.assertContains(response, 'href="' + expected_back + '"')

    def test_old_section_bookmarks_open_their_own_workspace(self):
        for tab in ("backups", "activity", "history", "export", "import"):
            with self.subTest(tab=tab):
                self.assert_workspace(self.client.get(self.url, {"tab": tab}),
                                      "import" if tab == "import" else "export")

    def test_workspace_titles_and_return_links_are_clear(self):
        for workflow, title in (("export", "Create a backup"), ("import", "Restore from ZIP")):
            with self.subTest(workflow=workflow):
                response = self.client.get(reverse("admin_backup_" + workflow))
                self.assert_workspace(response, workflow)
                self.assertContains(response, "<h1>" + title + "</h1>", html=True)
                self.assertContains(response, "Back to Maintenance")

    def test_existing_history_bookmarks_keep_prepared_backup_links_available(self):
        for alias in ("history", "transfers"):
            with self.subTest(alias=alias):
                response = self.client.get(self.url, {"tab": alias})
                self.assert_workspace(response, "export")
                self.assertContains(response, 'id="prepared-backups"')
                self.assertNotContains(response, 'id="import-history"')

    def test_backup_tasks_return_to_maintenance_without_a_mixed_task_page(self):
        for workflow in ("export", "import"):
            with self.subTest(workflow=workflow):
                response = self.client.get(reverse("admin_backup_" + workflow))
                self.assert_workspace(response, workflow)
                self.assertNotContains(response, 'href="' + self.url + '?tab=backups"')

    def test_export_activity_remains_with_export_and_never_displays_imports(self):
        self.operations.return_value = [{
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "running",
        }]
        response = self.client.get(reverse("admin_backup_export"))
        self.assert_workspace(response, "export")
        self.assertContains(response, 'id="backup-history"')
        self.assertNotContains(response, 'id="import-history"')

    def test_operation_details_return_to_their_own_workspace_for_every_old_origin(self):
        operation = {
            "id": self.operation_id, "kind": "export", "profile": "database",
            "status": "completed", "downloadable": True, "package_bytes": 2048,
        }
        with patch.object(service, "get_operation", return_value=operation):
            for origin in (None, "backups", "unknown", "https://external.example/", "databases", "activity"):
                with self.subTest(origin=origin):
                    query = {"operation": self.operation_id}
                    if origin:
                        query["from"] = origin
                    response = self.client.get(self.url, query)
                    self.assert_workspace(response, "export")
                    self.assertContains(response, "<h1>Backup ready to download</h1>", html=True)
                    self.assertContains(response, "Back to Create backup")
                    self.assertContains(response, reverse("admin_data_transfer_download", args=[self.operation_id]))

    def test_activity_links_open_the_matching_operation_workspace(self):
        self.operations.return_value = [{
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "running",
        }]
        response = self.client.get(self.url, {"tab": "activity"})
        self.assertContains(response, 'href="{}?operation={}#transfer-operation"'.format(
            reverse("admin_backup_export"), self.operation_id,
        ))
        self.assertNotContains(response, 'href="' + reverse("admin_backup_import") + '?operation=')

    def test_refresh_and_maintenance_keep_the_activity_return_destination(self):
        operation = {
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "running",
            "downloadable": False, "runner_active": True, "recoverable": False, "cancellable": False,
        }
        with patch.object(service, "get_operation", return_value=operation):
            response = self.client.get(self.url, {"operation": self.operation_id, "from": "activity"})
        self.assert_workspace(response, "export")
        self.assertContains(response, "<h1>Creating your backup</h1>", html=True)
        refresh = urlsplit(response.context["operation_refresh_url"])
        self.assertEqual(refresh.path, reverse("admin_backup_export"))
        self.assertEqual(parse_qs(refresh.query)["from"], ["activity"])
        maintenance_query = parse_qs(urlsplit(response.context["maintenance_url"]).query)
        destination = urlsplit(maintenance_query["next"][0])
        self.assertEqual(destination.path, reverse("admin_backup_export"))
        self.assertEqual(parse_qs(destination.query)["from"], ["activity"])
        self.assertEqual(parse_qs(destination.query)["operation"], [self.operation_id])

    def test_database_manager_origin_survives_refresh_maintenance_and_child_actions(self):
        operation = {
            "id": self.operation_id, "kind": "import", "profile": "database", "status": "completed",
            "result": {"verified": True, "target_database": "qc_restored"},
        }
        with patch.object(service, "get_operation", return_value=operation):
            response = self.client.get(self.url, {"operation": self.operation_id, "from": "databases"})
        self.assert_workspace(response, "import")
        for key in ("operation_refresh_url", "transfer_action_url"):
            destination = urlsplit(response.context[key])
            self.assertEqual(destination.path, reverse("admin_backup_import"))
            self.assertEqual(parse_qs(destination.query)["from"], ["databases"])
        maintenance_query = parse_qs(urlsplit(response.context["maintenance_url"]).query)
        destination = urlsplit(maintenance_query["next"][0])
        self.assertEqual(destination.path, reverse("admin_backup_import"))
        self.assertEqual(parse_qs(destination.query)["from"], ["databases"])
        self.assertEqual(parse_qs(destination.query)["operation"], [self.operation_id])

    def test_database_manager_origin_keeps_transfer_review_on_the_import_handler(self):
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
            self.assert_workspace(response, "import")
            self.assertContains(response, "<h1>Review database switch</h1>", html=True)
            response = self.client.post(response.context["transfer_action_url"], payload)
        self.assert_workspace(response, "import")
        self.assertContains(response, "<h1>Review database switch</h1>", html=True)
        self.assertEqual(review.call_count, 2)
        activate.assert_not_called()
        select.assert_not_called()

    def test_switch_review_form_keeps_its_saved_return_origin(self):
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
        self.assert_workspace(response, "import")
        self.assertContains(response, 'action="' + reverse("admin_backup_import") + '?from=activity"')
        activate.assert_not_called()

    def test_switch_back_stays_with_import_and_retains_its_confirmation_guards(self):
        actor = get_user_model().objects.get(username="database-navigation-admin")
        enabled = maintenance.enable(actor, expected_generation=0)
        maintenance.advance(expected_generation=enabled["generation"])
        generation = maintenance.read_status()["generation"]
        self.control_state.update(previous_database="qc_previous", revision=4, has_selection=True)
        response = self.client.get(reverse("admin_backup_import"), {"from": "activity"})
        self.assertContains(response, 'action="' + reverse("admin_backup_import") + '?from=activity"')
        with patch.object(service, "rollback_database") as rollback:
            response = self.client.post(reverse("admin_backup_import") + "?from=activity", {
                "action": "rollback_database", "rollback-generation": generation, "rollback-revision": 4,
                "rollback-destination_confirmation": "qc_previous", "rollback-confirmed_storage": "on",
            })
        self.assert_workspace(response, "import")
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

