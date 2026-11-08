"""Migration administration activation behavior."""

from django.urls import reverse

from qc_tool.frontend.dashboard.services import maintenance

from .fixtures import MigrationAdminTestCase


class MigrationActivationTests(MigrationAdminTestCase):
    def test_active_upgrade_after_reopening_does_not_claim_maintenance_is_still_on(self):
        self.overview.update(active_database="qc_tool_upgrade")
        self.overview["database"].update(state="ready", pending=[])
        self.overview["maintenance"]["phase"] = "off"
        self.get_operation.return_value = {**self.operation, "status": "completed", "runner_active": False,
                                          "maintenance_owned": False}
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "QC Tool is open on this database")
        self.assertContains(response, "History initialization complete; QC Tool is open")
        self.assertNotContains(response, "The existing v3.0.0 database was created without")
        self.assertContains(response, reverse("admin_storage"))
        self.assertContains(response, "Manage databases")
        self.assertNotContains(response, "Maintenance remains on.")


    def test_maintenance_action_preserves_the_current_migration_return_destination(self):
        self.get_operation.return_value = {**self.operation, "status": "completed", "runner_active": False}
        self.overview["maintenance"]["phase"] = "off"
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertEqual(response.context["migration_next_url"], response.context["maintenance_url"])
        self.assertIn("next=", response.context["migration_next_url"])
        self.assertIn(self.operation_id, response.context["migration_next_url"])


    def test_historical_active_operation_does_not_hide_new_pending_migrations(self):
        self.overview.update(active_database="qc_tool_upgrade")
        self.overview["database"].update(state="pending")
        self.get_operation.return_value = {**self.operation, "status": "completed", "runner_active": False,
                                          "maintenance_owned": False}
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Prepare the next release upgrade")
        self.assertContains(response, "still needs an upgrade for the current installation")


    def test_completed_upgrade_requires_switch_review_then_storage_confirmation(self):
        self.get_operation.return_value = {**self.operation, "status": "completed", "runner_active": False}
        response = self.client.post(self.url, {"action": "review_switch", "operation_id": self.operation_id})
        self.assertContains(response, "Choose the migration-managed database")
        self.assertNotContains(response, 'name="activation-password"')
        self.activate.assert_not_called()
        values = {"action": "activate", "operation_id": self.operation_id,
            "activation-review_hash": "c" * 64, "activation-generation": 5, "activation-revision": 0,
            "activation-destination_confirmation": "qc_tool_upgrade"}
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 400)
        self.activate.assert_not_called()
        values["activation-confirmed_storage"] = "on"
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 303)
        self.activate.assert_called_once_with(self.operation_id, actor=self.administrator,
            review_hash="c" * 64, generation=5, revision=0, destination_confirmation="qc_tool_upgrade",
            confirmed_storage=True, username="", password="")


    def test_owned_upgrade_disables_the_shared_maintenance_off_control(self):
        state = maintenance.enable("migration UI test", expected_generation=0)
        maintenance.advance(expected_generation=state["generation"])
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertFalse(response.context["maintenance"]["can_disable"])
        self.assertContains(response, "Complete or recover the current database operation")


    def test_selection_refuses_a_copy_whose_fresh_review_is_blocked(self):
        self.get_operation.return_value = {**self.operation, "status": "completed", "runner_active": False}
        self.activation_preview.return_value = {"can_apply": False, "blockers": ["Missing migration receipt."]}
        response = self.client.post(self.url, {"action": "activate", "operation_id": self.operation_id,
            "activation-review_hash": "c" * 64, "activation-generation": 5, "activation-revision": 0,
            "activation-destination_confirmation": "qc_tool_upgrade", "activation-confirmed_storage": "on"})
        self.assertContains(response, "not ready to select", status_code=409)
        self.activate.assert_not_called()


    def test_running_copy_cannot_skip_to_switch_review(self):
        response = self.client.post(self.url, {"action": "review_switch", "operation_id": self.operation_id})
        self.assertContains(response, "Complete and verify the upgraded copy", status_code=409)
        self.activation_preview.assert_not_called()
        self.activate.assert_not_called()
