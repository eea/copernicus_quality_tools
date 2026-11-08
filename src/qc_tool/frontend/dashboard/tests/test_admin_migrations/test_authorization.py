"""Migration administration authorization behavior."""

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from qc_tool.frontend.dashboard.services.database_navigation import maintenance_operation_url

from .fixtures import MigrationAdminTestCase


class MigrationAuthorizationTests(MigrationAdminTestCase):
    def test_staff_without_administrator_role_cannot_read_or_mutate(self):
        user = get_user_model().objects.create_user(username="staff", password="test", is_staff=True)
        get_user_model().objects.filter(pk=user.pk).update(is_staff=True)
        user.refresh_from_db()
        self.client.force_login(user)
        for method, url in (("get", self.url), ("post", self.url),
                            ("get", reverse("admin_migration_status", args=[self.operation_id]))):
            self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.start.assert_not_called()
        self.status.assert_not_called()


    def test_mutations_are_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.post(self.url, {"action": "review", "backup_id": self.backup_id}).status_code, 403)
        self.preview.assert_not_called()


    def test_status_mutation_methods_are_not_allowed(self):
        response = self.client.post(reverse("admin_migration_status", args=[self.operation_id]))
        self.assertEqual(response.status_code, 405)
        self.get_operation.assert_not_called()


    def test_upgrade_maintenance_pin_keeps_recovery_inside_migrations(self):
        self.assertEqual(maintenance_operation_url({"kind": "upgrade", "operation_id": self.operation_id}),
                         self.url + "?operation=" + self.operation_id)
