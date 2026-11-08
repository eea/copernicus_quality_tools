"""Migration administration recovery behavior."""

from django.urls import reverse

from .fixtures import MigrationAdminTestCase


class MigrationRecoveryTests(MigrationAdminTestCase):
    def test_unavailable_source_keeps_history_visible_without_unsafe_recovery_actions(self):
        self.overview["database"].update(state="unavailable", problems=["Source connection is unavailable."])
        self.overview.update(can_prepare=False, previous_database="previous_retained")
        self.get_operation.return_value = {**self.operation, "status": "recovery_required", "recoverable": True,
                                          "can_retry": True, "can_abandon": True, "runner_active": False}
        self.overview["operations"] = [self.get_operation.return_value]
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Restore database access before continuing")
        self.assertContains(response, "previous_retained")
        self.assertContains(response, self.operation_id)
        self.assertContains(response, "Upgrade history")
        self.assertNotContains(response, 'value="retry"')
        self.assertNotContains(response, "Keep failed copy and stop upgrade")
        response = self.client.post(self.url, {"operation_id": self.operation_id, "action": "retry"})
        self.assertEqual(response.status_code, 409)
        self.recover.assert_not_called()


    def test_queued_operation_uses_existing_polling_and_admin_status_route(self):
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, reverse("admin_migration_status", args=[self.operation_id]))
        self.assertContains(response, "data-transfer-status-url")
        self.assertNotContains(response, "Use upgraded database")
        self.activation_preview.assert_not_called()


    def test_status_only_returns_public_fields_and_never_mutates(self):
        self.get_operation.return_value = {**self.operation, "package_path": "/private/secret.zip", "password": "secret"}
        response = self.client.get(reverse("admin_migration_status", args=[self.operation_id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["runner_active"])
        self.assertNotContains(response, "/private/")
        self.assertNotContains(response, "secret")
        self.recover.assert_not_called()
        self.start.assert_not_called()


    def test_recovery_requires_explicit_post(self):
        self.get_operation.return_value = {**self.operation, "runner_active": False, "recoverable": True,
                                          "status": "recovery_required", "can_retry": True, "can_abandon": True}
        response = self.client.post(self.url, {"operation_id": self.operation_id, "action": "retry"})
        self.assertEqual(response.status_code, 303)
        self.recover.assert_called_once_with(self.operation_id, actor=self.administrator, action="retry")


    def test_uncertain_migration_does_not_offer_or_submit_retry(self):
        self.get_operation.return_value = {**self.operation, "status": "recovery_required", "runner_active": False,
            "recoverable": True, "can_retry": False, "can_abandon": True,
            "recovery_reason": "Migration execution is uncertain; automatic replay is unsafe."}
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertNotContains(response, 'value="retry"')
        self.assertContains(response, "automatic replay is unsafe")
        self.assertContains(response, "Keep failed copy and stop upgrade")
        self.assertNotContains(response, 'id="migration-backup-heading"')
        response = self.client.post(self.url, {"operation_id": self.operation_id, "action": "retry"})
        self.assertEqual(response.status_code, 409)
        self.recover.assert_not_called()


    def test_stopping_uncertain_upgrade_requires_confirmation_and_preserves_evidence(self):
        self.get_operation.return_value = {**self.operation, "status": "recovery_required", "runner_active": False,
                                          "recoverable": True, "can_retry": False, "can_abandon": True}
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Keep failed copy and stop upgrade")
        self.assertContains(response, "cannot automatically repeat an uncertain migration")
        values = {"operation_id": self.operation_id, "action": "abandon"}
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 400)
        self.recover.assert_not_called()
        values["confirmed_abandon"] = "on"
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 303)
        self.recover.assert_called_once_with(self.operation_id, actor=self.administrator, action="abandon")
