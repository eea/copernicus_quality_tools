"""The regular workspace exposes announcements for reading only."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.services.role_permissions import capability_content_type


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class AnnouncementAccessTests(TestCase):
    def setUp(self):
        self.viewer = get_user_model().objects.create_user(username="announcement-viewer")
        self.manager = get_user_model().objects.create_user(username="announcement-manager")
        self.administrator = get_user_model().objects.create_superuser(username="announcement-admin")
        self.manager.user_permissions.add(Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        ))

    @patch(
        "qc_tool.frontend.dashboard.views.configuration.read_announcement",
        return_value="Service window\n<script>alert(1)</script>",
    )
    def test_every_workspace_viewer_gets_a_read_only_plain_text_message(self, _read):
        for user in (self.viewer, self.manager, self.administrator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse("announcement"))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "dashboard/configuration/announcement.html")
                self.assertContains(response, "Service window")
                self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
                self.assertNotContains(response, "<script>alert(1)</script>")
                self.assertNotContains(response, "Update announcement")
                self.assertNotContains(response, 'name="announcement_text"')

    @patch("qc_tool.frontend.dashboard.views.admin_notifications.write_announcement")
    def test_configuration_permission_alone_cannot_publish(self, write_announcement):
        for user in (self.viewer, self.manager):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.post(reverse("announcement_update"), {
                    "announcement_text": "Unauthorized change",
                }).status_code, 403)
        write_announcement.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.admin_notifications.write_announcement")
    def test_workspace_has_no_mutation_alias(self, write_announcement):
        self.client.force_login(self.administrator)
        self.assertEqual(self.client.post("/announcement/update/", {
            "announcement_text": "Old form",
        }).status_code, 404)
        self.assertEqual(self.client.post(reverse("announcement")).status_code, 405)
        write_announcement.assert_not_called()
