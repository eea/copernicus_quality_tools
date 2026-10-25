"""HTTP management actions preserve service-owned destructive/switch guards."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.database.transfers import service
from qc_tool.frontend.accounts.authorization.roles import Role


@override_settings(MAINTENANCE_MODE=False)
class AdminDatabaseManagementTests(TestCase):
    operation_id = "b88a3212-2a85-4fe2-89ea-7174356ac835"
    target = "qc_restore_b88a32122a854fe289ea7174356ac835"

    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
                                           QC_TOOL_TRANSFER_DIR=directory / "transfers"))
        self.actor = get_user_model().objects.create_user(username="database-manager")
        self.actor.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(self.actor)
        self.url = reverse("admin_data_transfer") + "?tab=databases"
        self.inventory = {
            "supported": True, "available": True, "active_database": "qc_original", "revision": 3,
            "configured_database": "qc_original", "generation": 7, "maintenance_ready": True,
            "databases": [
                {"database": "qc_original", "active": True, "configured": True, "label": "In use now",
                 "present": True, "can_inspect": True, "bytes": 1024},
                {"database": self.target, "operation_id": self.operation_id, "managed": True,
                 "present": True, "can_inspect": True, "completed_restore": True, "label": "Restored copy",
                 "can_delete": True, "can_review_selection": True, "bytes": 2048},
            ],
        }
        self.inventory_mock = self.enterContext(patch.object(service, "database_inventory", side_effect=lambda **kw: deepcopy(self.inventory)))
        self.delete = self.enterContext(patch.object(service, "delete_restore_database"))
        self.select = self.enterContext(patch.object(service, "select_database", return_value={"revision": 4}))
        self.review = self.enterContext(patch.object(service, "review_database_selection", return_value={
            "source_database": "qc_original", "target_database": self.target,
            "revision": 3, "review_hash": "a" * 64, "can_apply": True, "requires_credentials": False,
        }))

    def confirmation(self, **changes):
        prefix = "delete-" + self.operation_id + "-"
        return {"action": "delete_database", "operation_id": self.operation_id,
                prefix + "generation": 7, prefix + "revision": 3,
                prefix + "destination_confirmation": self.target,
                **changes}

    def test_listing_separates_active_database_and_backup_files_without_transfer_probes(self):
        with patch.object(service, "schema_readiness") as schema, patch.object(service, "database_availability") as tools:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Manage databases</h1>", html=True)
        self.assertContains(response, "qc_original")
        self.assertContains(response, "Only one database is active at a time")
        self.assertContains(response, "&amp;inspect=" + self.target + "#database-inspection")
        self.assertContains(response, "Review switch")
        self.assertContains(response, "Backup ZIPs")
        self.assertContains(response, "active database is protected from deletion")
        schema.assert_not_called()
        tools.assert_not_called()
        self.delete.assert_not_called()
        self.select.assert_not_called()

    def test_restore_details_link_returns_to_manage_databases(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'href="' + reverse("admin_data_transfer") + '?operation='
                            + self.operation_id + '&amp;from=databases#transfer-operation"')
        self.select.assert_not_called()
        self.delete.assert_not_called()

    def test_delete_button_submits_the_exact_target_without_typing_or_an_acknowledgement(self):
        response = self.client.get(self.url)
        field_name = "delete-" + self.operation_id + "-destination_confirmation"
        self.assertContains(response, '<input type="hidden" name="' + field_name + '" value="' + self.target + '"')
        self.assertNotContains(response, "Type the database name")
        self.assertNotContains(response, "confirmed_delete")
        self.delete.assert_not_called()

    def test_get_query_cannot_delete_or_select_database(self):
        self.client.get(self.url + "&action=delete_database&operation_id=" + self.operation_id + "&deleted=1")
        self.delete.assert_not_called()
        self.select.assert_not_called()

    def test_unknown_or_tampered_delete_targets_do_not_reach_the_service(self):
        field_name = "delete-" + self.operation_id + "-destination_confirmation"
        missing_target = self.confirmation()
        del missing_target[field_name]
        for values in (self.confirmation(operation_id="unknown"), missing_target,
                       self.confirmation(**{field_name: "wrong"})):
            with self.subTest(values=values):
                response = self.client.post(self.url, values)
                self.assertIn(response.status_code, {400, 409})
        self.delete.assert_not_called()

    def test_delete_without_typed_confirmation_is_post_redirect_get_and_preserves_service_arguments(self):
        response = self.client.post(self.url, self.confirmation())
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], self.url)
        self.assertIn("no-store", response["Cache-Control"])
        self.delete.assert_called_once_with(self.operation_id, actor=self.actor, generation=7, revision=3,
                                            destination_confirmation=self.target)

    def test_missing_delete_version_tokens_do_not_reach_the_service(self):
        for token in ("generation", "revision"):
            values = self.confirmation()
            del values["delete-" + self.operation_id + "-" + token]
            with self.subTest(token=token):
                response = self.client.post(self.url, values)
                self.assertEqual(response.status_code, 400)
        self.delete.assert_not_called()

    def test_stale_delete_tokens_reach_the_service_unchanged_and_surface_its_blocker(self):
        self.delete.side_effect = service.TransferError("Database state changed. Reload the list before deleting.")
        values = self.confirmation(**{"delete-" + self.operation_id + "-generation": 6,
                                      "delete-" + self.operation_id + "-revision": 2})
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Database state changed", status_code=409)
        self.delete.assert_called_once_with(self.operation_id, actor=self.actor, generation=6, revision=2,
                                            destination_confirmation=self.target)
        self.select.assert_not_called()

    def test_busy_action_has_live_waiting_feedback_without_replaying_the_request(self):
        from qc_tool.database.transfers.errors import TransferBusy
        self.delete.side_effect = TransferBusy("Another maintenance action is in progress.")
        response = self.client.post(self.url, self.confirmation())
        self.assertContains(response, "Another action is finishing", status_code=409)
        self.assertContains(response, 'data-admin-busy-url="' + reverse("admin_maintenance") + '"', status_code=409)
        self.assertContains(response, "Your request will not be retried automatically", status_code=409)
        self.assertContains(response, "qc-admin-spinner", status_code=409)
        self.assertContains(response, 'href="' + self.url.replace("&", "&amp;") + '" data-admin-busy-refresh', status_code=409)
        self.assertEqual(self.delete.call_count, 1)

    def test_busy_feedback_survives_service_error_translation(self):
        from qc_tool.frontend.dashboard.services.maintenance import MaintenanceBusy
        problem = service.TransferError("Another maintenance action is in progress.")
        problem.__cause__ = MaintenanceBusy(str(problem))
        self.review.side_effect = problem
        response = self.client.post(self.url, {"action": "review_selection", "target_database": self.target})
        self.assertContains(response, "Another action is finishing", status_code=409)
        self.select.assert_not_called()
        self.delete.assert_not_called()

    def test_switch_review_is_read_only_until_explicit_confirmation(self):
        response = self.client.post(self.url, {"action": "review_selection", "target_database": self.target})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Review database switch</h1>", html=True)
        self.assertContains(response, "Back to Manage databases")
        self.assertNotContains(response, 'id="database-copies-heading"')
        html = response.content.decode()
        self.assertLess(html.index('id="database-selection-review"'), html.index("<h1>Review database switch</h1>"))
        self.assertEqual(response.context["database_back_url"], self.url)
        self.assertEqual(response.context["database_breadcrumbs"][-2], {
            "label": "Manage databases", "url": self.url,
        })
        self.assertContains(response, "In use now")
        self.assertContains(response, "Use after switching")
        self.assertContains(response, 'name="selection-review_hash" value="' + "a" * 64 + '"')
        self.assertContains(response, '<input type="hidden" name="selection-destination_confirmation" value="' + self.target + '"')
        self.assertNotContains(response, "Type the database name")
        self.select.assert_not_called()
        self.delete.assert_not_called()

    def test_switch_confirmation_preserves_source_cookie_before_service_changes_pointer(self):
        with patch("qc_tool.frontend.dashboard.views.admin_databases.login_without_database_writes") as login:
            response = self.client.post(self.url, {"action": "select_database", "target_database": self.target,
                "selection-generation": 7, "selection-revision": 3, "selection-review_hash": "a" * 64,
                "selection-destination_confirmation": self.target, "selection-confirmed_storage": "on"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], self.url)
        self.assertEqual(login.call_args.args[1], self.actor)
        self.select.assert_called_once_with(self.target, actor=self.actor, generation=7, revision=3,
            review_hash="a" * 64, destination_confirmation=self.target, confirmed_storage=True, username="", password="")

    def test_missing_or_tampered_switch_target_does_not_select_a_database(self):
        values = {"action": "select_database", "target_database": self.target,
                  "selection-generation": 7, "selection-revision": 3, "selection-review_hash": "a" * 64,
                  "selection-confirmed_storage": "on"}
        for destination in (None, "qc_unrelated_database"):
            with self.subTest(destination=destination):
                payload = dict(values)
                if destination is not None:
                    payload["selection-destination_confirmation"] = destination
                response = self.client.post(self.url, payload)
                self.assertEqual(response.status_code, 400)
        self.select.assert_not_called()
        self.delete.assert_not_called()

    def test_deletion_failure_keeps_delete_available_and_reports_service_blocker(self):
        self.delete.side_effect = service.TransferError("The active database changed. Review the list again.")
        response = self.client.post(self.url, self.confirmation())
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "active database changed", status_code=409)
        self.assertContains(response, 'name="action" value="delete_database"', status_code=409)
        self.assertContains(response, 'name="operation_id" value="' + self.operation_id + '"', status_code=409)

    def test_inspection_reports_current_estimates_without_selecting(self):
        with patch.object(service, "database_details", return_value={"database": self.target, "bytes": 2048,
                "table_count": 1, "schema": {"ready": True}, "counts_note": "Counts are estimates.",
                "tables": [{"schema": "public", "name": "auth_user", "estimated_rows": None, "bytes": 2048}]}) as details:
            response = self.client.get(self.url + "&inspect=" + self.target)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Inspect database</h1>", html=True)
        self.assertContains(response, "Back to Manage databases")
        self.assertNotContains(response, 'id="database-copies-heading"')
        html = response.content.decode()
        self.assertLess(html.index('id="database-inspection"'), html.index("<h1>Inspect database</h1>"))
        self.assertEqual(response.context["database_back_url"], self.url)
        self.assertEqual(response.context["database_breadcrumbs"][-2], {
            "label": "Manage databases", "url": self.url,
        })
        details.assert_called_once_with(self.target, actor=self.actor)
        self.assertContains(response, "Counts are estimates.")
        self.assertContains(response, "Unavailable")
        self.assertContains(response, 'name="action" value="review_selection"')
        self.review.assert_not_called()
        self.select.assert_not_called()

    def test_inventory_error_does_not_misidentify_database_engine(self):
        self.inventory_mock.side_effect = service.TransferError("Database server unavailable.")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Database list unavailable", status_code=409)
        self.assertNotContains(response, "requires PostgreSQL", status_code=409)

    def test_non_administrator_cannot_list_or_submit_database_actions(self):
        user = get_user_model().objects.create_user(username="ordinary-user")
        self.client.force_login(user)
        self.inventory_mock.reset_mock()
        for method in (self.client.get, self.client.post):
            response = method(self.url)
            self.assertIn(response.status_code, {302, 403})
        self.inventory_mock.assert_not_called()
        self.delete.assert_not_called()
        self.select.assert_not_called()

    def test_database_deletion_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        response = client.post(self.url, self.confirmation())
        self.assertEqual(response.status_code, 403)
        self.delete.assert_not_called()
