"""Admin notification publication retains permissions, CSRF and safe storage."""

from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.common import CONFIG
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.role_permissions import capability_content_type
from qc_tool.frontend.dashboard.services.configuration import (
    AnnouncementStorageError,
    MAX_ANNOUNCEMENT_BYTES,
)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class AdminNotificationTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings_override = override_settings(
            QC_TOOL_MAINTENANCE_DIR=temporary.name + "/maintenance",
            QC_TOOL_TRANSFER_DIR=temporary.name + "/transfers",
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.announcement_path = Path(temporary.name) / "announcement.txt"
        configuration = patch.dict(CONFIG, announcement_path=str(self.announcement_path))
        configuration.start()
        self.addCleanup(configuration.stop)
        self.administrator = get_user_model().objects.create_superuser(username="notification-admin")
        self.client.force_login(self.administrator)
        self.url = reverse("admin_notifications")
        self.update_url = reverse("announcement_update")

    def test_admin_routes_preview_existing_message_and_reuse_chrome(self):
        self.announcement_path.write_text("Planned outage\n<script>alert(1)</script>", encoding="utf-8")
        response = self.client.get(self.url)
        self.assertEqual(self.url, "/admin/notifications/")
        self.assertEqual(self.update_url, "/admin/notifications/update/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/base_site.html")
        self.assertTemplateUsed(response, "dashboard/shared/announcements/current.html")
        self.assertContains(response, "Current announcement")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, "Publish announcement")
        self.assertContains(response, "Remove announcement")
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, "dashboard/css/ui/actions.css")
        self.assertNotContains(response, 'maxlength="65536"')

    def test_unauthenticated_requests_recover_inside_admin(self):
        self.client.logout()
        for method, url in (("get", self.url), ("post", self.update_url)):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertRedirects(response, reverse("admin_login") + "?next=" + url,
                                     fetch_redirect_response=False)

    def test_staff_without_qc_admin_role_cannot_read_or_publish(self):
        staff = get_user_model().objects.create_user(username="notification-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        staff.user_permissions.add(Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        ))
        self.client.force_login(staff)
        for method, url in (("get", self.url), ("post", self.update_url)):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(response, "admin/qc_tool_error.html")
        self.assertFalse(self.announcement_path.exists())

    def test_qc_admin_role_can_publish(self):
        administrator = get_user_model().objects.create_user(username="notification-role-admin")
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)
        response = self.client.post(self.update_url, {"announcement_text": "Planned maintenance"})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(self.announcement_path.read_text(encoding="utf-8"), "Planned maintenance")
        self.assertContains(self.client.get(reverse("announcement")), "Planned maintenance")

    def test_clear_explicitly_removes_the_message(self):
        self.announcement_path.write_text("Old notice", encoding="utf-8")
        response = self.client.post(self.update_url, {
            "action": "clear", "announcement_text": "Unsaved textarea value",
        })
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(self.announcement_path.read_text(encoding="utf-8"), "")
        response = self.client.get(self.url)
        self.assertContains(response, "There is no active announcement.")
        self.assertNotContains(response, ">Remove announcement</button>")

    def test_empty_publish_also_clears_current_announcement(self):
        self.announcement_path.write_text("Old notice", encoding="utf-8")
        self.assertEqual(self.client.post(self.update_url, {"announcement_text": ""}).status_code, 302)
        self.assertEqual(self.announcement_path.read_text(encoding="utf-8"), "")

    def test_utf8_validation_preserves_submitted_text_and_current_message(self):
        self.announcement_path.write_text("Published message", encoding="utf-8")
        submitted = "é" * ((MAX_ANNOUNCEMENT_BYTES // 2) + 1)
        response = self.client.post(self.update_url, {"announcement_text": submitted})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["announcement_form"], "announcement_text",
                             "The announcement must be 64 KiB or smaller when encoded as UTF-8.")
        self.assertEqual(response.context["announcement_form"]["announcement_text"].value(), submitted)
        self.assertContains(response, 'aria-invalid="true"')
        self.assertEqual(self.announcement_path.read_text(encoding="utf-8"), "Published message")

    def test_exact_utf8_byte_limit_is_published(self):
        submitted = "é" * (MAX_ANNOUNCEMENT_BYTES // 2)
        response = self.client.post(self.update_url, {"announcement_text": submitted})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(self.announcement_path.read_text(encoding="utf-8"), submitted)

    @patch("qc_tool.frontend.dashboard.views.admin_notifications.write_announcement",
           side_effect=AnnouncementStorageError)
    def test_storage_failure_preserves_the_editor_for_retry(self, _write):
        response = self.client.post(self.update_url, {"announcement_text": "Retry this message"})
        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "admin/notifications.html")
        self.assertContains(response, "The announcement could not be saved.", status_code=503)
        self.assertEqual(response.context["announcement_form"]["announcement_text"].value(), "Retry this message")

    def test_csrf_and_http_methods_are_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.post(self.update_url, {"announcement_text": "Missing CSRF"}).status_code, 403)
        self.assertEqual(self.client.get(self.update_url).status_code, 405)
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.assertFalse(self.announcement_path.exists())

    def test_unknown_action_does_not_change_the_message(self):
        response = self.client.post(self.update_url, {"action": "unknown", "announcement_text": "No"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.announcement_path.exists())

    @override_settings(MAINTENANCE_MODE=True)
    def test_maintenance_preserves_preview_and_blocks_publication(self):
        self.announcement_path.write_text("Existing notice", encoding="utf-8")
        response = self.client.get(self.url)
        self.assertContains(response, "Existing notice")
        self.assertContains(response, 'data-maintenance-write disabled')
        response = self.client.post(self.update_url, {"announcement_text": "Blocked"})
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'href="{}"'.format(reverse("admin:index")), status_code=503)
        self.assertEqual(self.announcement_path.read_text(encoding="utf-8"), "Existing notice")
