"""Permission and method contracts for the shared announcement surface."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)
from qc_tool.frontend.dashboard.services.configuration import (
    MAX_ANNOUNCEMENT_BYTES,
)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class AnnouncementAccessTests(TestCase):
    """All viewers may read; only configuration managers may mutate."""

    def setUp(self):
        self.viewer = get_user_model().objects.create_user(
            username="announcement-viewer",
            password="test-password",
        )
        self.manager = get_user_model().objects.create_user(
            username="announcement-manager",
            password="test-password",
        )
        manage_configuration = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_CONFIGURATION.value,
        )
        self.manager.user_permissions.add(manage_configuration)

    @patch(
        "qc_tool.frontend.dashboard.views.read_announcement",
        return_value="Service window\n<script>alert(1)</script>",
    )
    def test_default_user_can_read_plain_text_without_editor(self, _read):
        self.client.force_login(self.viewer)

        response = self.client.get(reverse("announcement"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/announcement.html")
        self.assertContains(response, "Service window")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, "Update announcement")
        self.assertNotContains(
            response,
            'action="{}"'.format(reverse("announcement_update")),
        )

    @patch(
        "qc_tool.frontend.dashboard.views.read_announcement",
        return_value="Existing message",
    )
    def test_configuration_manager_sees_post_editor(self, _read):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("announcement"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Update announcement")
        self.assertContains(
            response,
            '<form method="post" action="{}">'.format(
                reverse("announcement_update")
            ),
        )
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, "The message may use up to 64 KiB")
        self.assertNotContains(response, 'maxlength="65536"')

    @patch("qc_tool.frontend.dashboard.views.write_announcement")
    def test_default_user_cannot_update_announcement(self, write_announcement):
        self.client.force_login(self.viewer)

        response = self.client.post(
            reverse("announcement_update"),
            {"announcement_text": "Unauthorized change"},
        )

        self.assertEqual(response.status_code, 403)
        write_announcement.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.write_announcement")
    def test_configuration_manager_can_update_via_post_only(
        self,
        write_announcement,
    ):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("announcement_update"),
            {"announcement_text": "Planned maintenance"},
        )

        self.assertRedirects(
            response,
            reverse("announcement"),
            fetch_redirect_response=False,
        )
        write_announcement.assert_called_once()
        self.assertEqual(
            write_announcement.call_args.args[1],
            "Planned maintenance",
        )

        self.assertEqual(
            self.client.get(reverse("announcement_update")).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(reverse("announcement")).status_code,
            405,
        )

    @patch(
        "qc_tool.frontend.dashboard.views.read_announcement",
        return_value="Published message",
    )
    @patch("qc_tool.frontend.dashboard.views.write_announcement")
    def test_oversized_utf8_message_has_field_error_and_is_preserved(
        self,
        write_announcement,
        _read_announcement,
    ):
        self.client.force_login(self.manager)
        submitted = "é" * ((MAX_ANNOUNCEMENT_BYTES // 2) + 1)

        response = self.client.post(
            reverse("announcement_update"),
            {"announcement_text": submitted},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["announcement_form"],
            "announcement_text",
            "The announcement must be 64 KiB or smaller when encoded as "
            "UTF-8.",
        )
        self.assertEqual(
            response.context["announcement_form"]["announcement_text"].value(),
            submitted,
        )
        self.assertEqual(response.context["announcement"], "Published message")
        self.assertContains(response, 'aria-invalid="true"')
        write_announcement.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.write_announcement")
    def test_exact_utf8_byte_limit_is_accepted(self, write_announcement):
        self.client.force_login(self.manager)
        submitted = "é" * (MAX_ANNOUNCEMENT_BYTES // 2)

        response = self.client.post(
            reverse("announcement_update"),
            {"announcement_text": submitted},
        )

        self.assertRedirects(
            response,
            reverse("announcement"),
            fetch_redirect_response=False,
        )
        write_announcement.assert_called_once()
        self.assertEqual(write_announcement.call_args.args[1], submitted)
