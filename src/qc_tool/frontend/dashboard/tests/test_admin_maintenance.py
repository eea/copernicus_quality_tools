"""Admin maintenance controls preserve role, CSRF and readiness boundaries."""

import tempfile
from html.parser import HTMLParser
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client
from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.urls import get_script_prefix, set_script_prefix

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.views.admin_maintenance import maintenance_control


class _MaintenanceControls(HTMLParser):
    """Inspect the dedicated controls without including the shared banner."""

    def __init__(self, response):
        super().__init__()
        self.depth = 0
        self.control_depth = None
        self.elements = []
        self.headings = []
        self.heading = None
        self.feed(response.content.decode(response.charset))
        if not self.elements:
            raise AssertionError("The dedicated maintenance controls were not rendered.")

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "div":
            self.depth += 1
            if "data-maintenance-control" in attributes:
                self.control_depth = self.depth
        if self.control_depth is not None:
            self.elements.append((tag, attributes))
            if tag == "h2":
                self.heading = []

    def handle_data(self, value):
        if self.heading is not None:
            self.heading.append(value)

    def handle_endtag(self, tag):
        if tag == "h2" and self.heading is not None:
            self.headings.append(" ".join("".join(self.heading).split()))
            self.heading = None
        if tag == "div":
            if self.depth == self.control_depth:
                self.control_depth = None
            self.depth -= 1

    def named(self, name):
        return [attributes for tag, attributes in self.elements
                if attributes.get("name") == name]


class AdminMaintenanceTests(TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        settings_override = override_settings(
            QC_TOOL_MAINTENANCE_DIR=temporary_directory.name + "/maintenance",
            QC_TOOL_TRANSFER_DIR=temporary_directory.name + "/transfers",
            MAINTENANCE_MODE=False,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.administrator = get_user_model().objects.create_superuser(
            username="maintenance-administrator",
            email="maintenance@example.test",
            password="test-password",
        )
        self.client.force_login(self.administrator)
        self.url = reverse("admin_maintenance")

    def status(self, *, phase="off", generation=0):
        return {
            "enabled": phase != "off",
            "phase": phase,
            "generation": generation,
            "blockers": [],
            "actor": "maintenance-administrator",
            "changed_at": "2026-10-20T10:00:00+00:00",
            "readiness_checked_at": "2026-10-20T10:05:00+00:00" if phase == "ready" else "",
        }

    def test_administrator_can_discover_controls_on_admin_index(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="{}"'.format(self.url))
        self.assertContains(response, "Maintenance settings")

    def test_maintenance_landing_owns_backups_restore_and_history(self):
        with (patch.object(maintenance, "enable") as enable,
              patch.object(maintenance, "disable") as disable,
              patch.object(maintenance, "advance") as advance):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["admin_section"], "maintenance")
        self.assertEqual(_MaintenanceControls(response).headings, ["Maintenance mode", "Backups"])
        self.assertContains(response, 'href="' + reverse("admin_backup_export") + '"')
        self.assertContains(response, 'href="' + reverse("admin_backup_import") + '"')
        self.assertNotContains(response, "Manage databases")
        self.assertNotContains(response, "Backup history")
        self.assertContains(response, "stops queued and running QC jobs")
        self.assertContains(response, "users must submit interrupted jobs again")
        self.assertNotContains(response, 'aria-label="Maintenance tasks"')
        self.assertNotContains(response, "Technical details")
        enable.assert_not_called()
        disable.assert_not_called()
        advance.assert_not_called()

    def test_qc_administrator_role_can_access_controls(self):
        administrator = get_user_model().objects.create_user(
            username="role-administrator", password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Turn on maintenance")

    def test_product_manager_cannot_access_or_discover_controls(self):
        manager = get_user_model().objects.create_user(
            username="maintenance-product-manager", password="test-password",
        )
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(manager)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        with patch.object(maintenance, "enable") as enable:
            self.assertEqual(
                self.client.post(
                    self.url, {"action": "enable", "generation": 0},
                ).status_code,
                403,
            )
            enable.assert_not_called()
        self.assertNotContains(
            self.client.get(reverse("admin:index")), "Manage maintenance mode",
        )

    def test_staff_without_administrator_role_is_denied(self):
        staff = get_user_model().objects.create_user(username="maintenance-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        self.client.force_login(staff)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_request_uses_admin_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(
            response, reverse("admin_login") + "?next=" + self.url,
            fetch_redirect_response=False,
        )

    def test_csrf_is_required_to_change_state(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        with patch.object(maintenance, "enable") as enable:
            response = client.post(
                self.url, {"action": "enable", "generation": 0},
            )

        self.assertEqual(response.status_code, 403)
        enable.assert_not_called()

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_get_does_not_advance_or_write_application_state(self):
        with (
            patch.object(maintenance, "advance") as advance,
            patch.object(maintenance, "enable") as enable,
            patch.object(maintenance, "disable") as disable,
            CaptureQueriesContext(connection) as captured,
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        advance.assert_not_called()
        enable.assert_not_called()
        disable.assert_not_called()
        mutations = [
            query["sql"] for query in captured
            if query["sql"].lstrip().upper().startswith(
                ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "),
            )
        ]
        self.assertEqual(mutations, [])

    def test_enable_advances_the_new_generation(self):
        with (
            patch.object(maintenance, "enable", return_value=self.status(phase="stopping", generation=4)) as enable,
            patch.object(maintenance, "advance") as advance,
        ):
            response = self.client.post(
                self.url, {"action": "enable", "generation": "3"},
            )

        self.assertEqual(response.status_code, 200)
        enable.assert_called_once_with(self.administrator, expected_generation=3)
        advance.assert_called_once_with(expected_generation=4)
        self.assertContains(response, "Maintenance mode enabled.")

    def test_automatic_progress_uses_the_stopping_only_guard(self):
        with (
            patch.object(maintenance, "read_status", return_value=self.status(phase="stopping", generation=4)),
            patch.object(maintenance, "advance") as advance,
        ):
            response = self.client.post(
                self.url, {"action": "progress", "generation": 4},
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        advance.assert_called_once_with(expected_generation=4, stopping_only=True)
        self.assertTrue(response.json()["poll"])
        self.assertEqual(response.json()["generation"], 4)
        self.assertIn("no-store", response["Cache-Control"])

    def test_get_json_status_does_not_advance_or_repeat_an_administrator_action(self):
        with (
            patch.object(maintenance, "advance") as advance,
            patch.object(maintenance, "enable") as enable,
            patch.object(maintenance, "disable") as disable,
        ):
            response = self.client.get(self.url, HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phase"], "off")
        self.assertFalse(response.json()["busy"])
        self.assertFalse(response.json()["poll"])
        self.assertEqual(response.json()["transfer_url"], "")
        self.assertIn("no-store", response["Cache-Control"])
        for action in (advance, enable, disable):
            action.assert_not_called()

    def test_get_status_recognizes_each_admission_lock_as_busy(self):
        for control_busy, execution_busy in ((True, False), (False, True)):
            with (
                self.subTest(control_busy=control_busy, execution_busy=execution_busy),
                patch.object(maintenance, "control_active", return_value=control_busy),
                patch("qc_tool.database.transfers.store.execution_active", return_value=execution_busy),
            ):
                response = self.client.get(self.url, HTTP_ACCEPT="application/json")

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["busy"])
            self.assertTrue(response.json()["poll"])
            self.assertEqual(response["Retry-After"], "3")

    def test_get_busy_status_links_only_to_the_owned_admin_transfer(self):
        operation_id = "a2b12963-17de-45d0-804e-f4c35b1c4d05"
        with patch(
            "qc_tool.frontend.dashboard.views.admin_maintenance.active_operation",
            return_value={"kind": "export", "operation_id": operation_id},
        ):
            response = self.client.get(self.url, HTTP_ACCEPT="application/json")

        self.assertTrue(response.json()["transfer_active"])
        self.assertEqual(response.json()["transfer_url"], reverse("admin_data_transfer") + "?operation=" + operation_id)

    def test_busy_progress_is_distinct_from_a_failed_connection(self):
        with (
            patch.object(maintenance, "read_status", return_value=self.status(phase="stopping", generation=4)),
            patch.object(maintenance, "advance", side_effect=maintenance.MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")),
        ):
            response = self.client.post(
                self.url, {"action": "progress", "generation": 4},
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["busy"])
        self.assertTrue(response.json()["poll"])

    def test_busy_control_has_a_live_waiting_notice_instead_of_a_plain_error(self):
        with patch.object(maintenance, "enable", side_effect=maintenance.MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")):
            response = self.client.post(self.url, {"action": "enable", "generation": 0})

        self.assertContains(response, "Another action is finishing", status_code=409)
        self.assertContains(response, "data-admin-busy-spinner", status_code=409)
        self.assertContains(response, 'data-admin-busy-url="{}"'.format(self.url), status_code=409)
        self.assertContains(response, 'disabled aria-describedby="admin-busy-heading"', status_code=409)
        self.assertNotContains(response, '<p class="errornote" role="alert">', status_code=409)

    def test_status_probe_failure_is_unavailable_without_starting_a_check(self):
        from qc_tool.database.transfers.errors import TransferError

        with (
            patch("qc_tool.database.transfers.store.execution_active", side_effect=TransferError("Transfer execution locking is unavailable.")),
            patch.object(maintenance, "advance") as advance,
        ):
            response = self.client.get(self.url, HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["poll"])
        self.assertFalse(response.json()["busy"])
        self.assertEqual(response.json()["error"], "Transfer execution locking is unavailable.")
        advance.assert_not_called()

    def test_unavailable_status_does_not_present_stopping_work_as_known(self):
        from qc_tool.database.transfers.errors import TransferError
        with patch("qc_tool.database.transfers.store.execution_active", side_effect=TransferError("Locking is unavailable.")):
            response = self.client.get(self.url)
        self.assertContains(response, "Maintenance status unavailable", status_code=503)
        self.assertNotContains(response, "Turning on maintenance", status_code=503)

    def test_busy_state_from_a_wrapped_transfer_error_remains_a_temporary_wait(self):
        from qc_tool.database.transfers.errors import TransferError
        error = TransferError("Another maintenance action is in progress.")
        error.__cause__ = maintenance.MaintenanceBusy(str(error))
        with patch("qc_tool.database.transfers.service.validate_resume_database", side_effect=error):
            response = self.client.post(self.url, {"action": "disable", "generation": 0})
        self.assertContains(response, "Another action is finishing", status_code=409)

    def test_automatic_progress_stops_after_readiness(self):
        with patch.object(maintenance, "advance") as advance:
            enabled = maintenance.enable(self.administrator, expected_generation=0)
            with patch.object(maintenance, "read_status", return_value=self.status(phase="ready", generation=enabled["generation"])):
                response = self.client.post(
                    self.url, {"action": "progress", "generation": enabled["generation"]},
                    HTTP_ACCEPT="application/json",
                )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["poll"])
        self.assertEqual(response.json()["phase"], "ready")
        advance.assert_called_once_with(expected_generation=enabled["generation"], stopping_only=True)

    def test_progress_conflict_exposes_current_state_without_success(self):
        with (
            patch.object(maintenance, "read_status", return_value=self.status(phase="ready", generation=5)),
            patch.object(maintenance, "advance", side_effect=maintenance.MaintenanceError("Maintenance state changed.")),
        ):
            response = self.client.post(
                self.url, {"action": "progress", "generation": 4},
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["generation"], 5)
        self.assertFalse(response.json()["poll"])
        self.assertEqual(response.json()["error"], "Maintenance state changed.")

    def test_progress_stops_when_a_transfer_owns_maintenance(self):
        with (
            patch.object(maintenance, "read_status", return_value=self.status(phase="ready", generation=4)),
            patch.object(maintenance, "advance", side_effect=maintenance.MaintenanceError("A transfer is in progress.")),
            patch("qc_tool.frontend.dashboard.views.admin_maintenance.active_operation", return_value={"kind": "import", "operation_id": "test-operation"}),
        ):
            response = self.client.post(
                self.url, {"action": "progress", "generation": 4},
                HTTP_ACCEPT="application/json",
            )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["poll"])
        self.assertTrue(response.json()["transfer_active"])

    def test_progress_fails_closed_when_status_cannot_be_read(self):
        with (
            patch.object(maintenance, "advance", side_effect=maintenance.MaintenanceError("Status unavailable.")),
            patch.object(maintenance, "read_status", side_effect=maintenance.MaintenanceError("Status unavailable.")),
        ):
            response = self.client.post(
                self.url, {"action": "progress", "generation": 4},
                HTTP_ACCEPT="application/json",
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["poll"])
        self.assertIsNone(response.json()["generation"])

    def test_automatic_progress_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        with patch.object(maintenance, "advance") as advance:
            response = client.post(
                self.url, {"action": "progress", "generation": 0},
                HTTP_ACCEPT="application/json",
            )
        self.assertEqual(response.status_code, 403)
        advance.assert_not_called()

    def test_administrator_can_complete_enable_and_disable_cycle(self):
        initial = maintenance.read_status()

        response = self.client.post(
            self.url,
            {"action": "enable", "generation": initial["generation"]},
        )

        self.assertEqual(response.status_code, 200)
        ready = maintenance.read_status()
        self.assertTrue(ready["enabled"])
        self.assertEqual(ready["phase"], "ready")
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        self.assertContains(self.client.get(self.url), "Maintenance is on")

        response = self.client.post(
            self.url,
            {"action": "disable", "generation": ready["generation"]},
        )

        self.assertContains(response, "Maintenance mode disabled.")
        self.assertFalse(maintenance.read_status()["enabled"])
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_stale_generation_is_displayed_without_success(self):
        with patch.object(
            maintenance, "disable",
            side_effect=maintenance.MaintenanceError("Maintenance state changed; reload this page."),
        ):
            response = self.client.post(
                self.url, {"action": "disable", "generation": "1"},
            )

        self.assertContains(
            response, "Maintenance state changed; reload this page.", status_code=409,
        )
        self.assertNotContains(response, "Maintenance mode disabled.", status_code=409)

    def test_missing_or_invalid_generation_never_mutates_state(self):
        with patch.object(maintenance, "enable") as enable:
            for generation in (None, "", "bad", "-1"):
                with self.subTest(generation=generation):
                    payload = {"action": "enable"}
                    if generation is not None:
                        payload["generation"] = generation
                    response = self.client.post(self.url, payload)
                    self.assertEqual(response.status_code, 400)
        enable.assert_not_called()

    def test_shared_disable_form_returns_to_the_admin_page_with_its_query(self):
        self.client.post(self.url, {"action": "enable", "generation": 0})
        ready = maintenance.read_status()
        return_url = reverse("admin_user_management") + "?q=somebody&tab=roles"

        response = self.client.post(self.url, {
            "action": "disable", "generation": ready["generation"],
            "next": return_url, "return_to_page": "1",
        })

        self.assertRedirects(response, return_url, fetch_redirect_response=False)
        self.assertFalse(maintenance.read_status()["enabled"])

    def render_inline_disable(self, return_url, **extra):
        request = RequestFactory().post(self.url, {
            "action": "disable", "generation": "4", "next": return_url,
            "return_to_page": "1", **extra,
        })
        request.user = self.administrator
        with (
            patch("qc_tool.database.transfers.service.validate_resume_database") as validate,
            patch.object(maintenance, "disable", return_value=self.status(generation=5)) as disable,
        ):
            response = maintenance_control(request)
        validate.assert_called_once_with(self.administrator)
        disable.assert_called_once_with(self.administrator, expected_generation=4)
        self.assertEqual(request.maintenance_status, self.status(generation=5))
        self.assertFalse(request.maintenance_active)
        return response

    def test_shared_disable_returns_to_admin_pages_outside_the_transfer_whitelist(self):
        for return_url in (
            reverse("admin:index"), reverse("boundaries") + "?boundary_type=eea",
            reverse("admin_notifications"),
            reverse("admin:auth_group_add"),
            reverse("admin:auth_user_change", args=[self.administrator.pk]),
        ):
            with self.subTest(return_url=return_url):
                response = self.render_inline_disable(return_url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], return_url)

    def test_shared_disable_rejects_unsafe_or_workspace_return_destinations(self):
        invalid_urls = (
            "", "/", "/deliveries/", "/administrator/", "/admin",
            "https://example.test/admin/", "https://testserver/admin/",
            "//example.test/admin/", "/\\example.test/admin/",
            "/admin/../deliveries/", "/admin/%2e%2e/deliveries/",
            "/admin/%252e%252e/deliveries/", "/admin/%255c../deliveries/",
            "/admin/?next=foo\nbar", "/admin/?q=foo\x7fbar",
            "/admin/%0d%0a/", "/admin/#fragment",
            "/admin/?q=" + "x" * 2048,
        )
        for return_url in invalid_urls:
            with self.subTest(return_url=return_url):
                response = self.render_inline_disable(return_url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], reverse("admin:index"))

    def test_shared_disable_respects_the_deployment_script_prefix(self):
        original_prefix = get_script_prefix()
        try:
            set_script_prefix("/qc/")
            return_url = reverse("admin_user_management") + "?q=somebody"
            response = self.render_inline_disable(return_url)
            self.assertEqual(response["Location"], return_url)
            for unsafe_url in ("/admin/users/", "/qc/admin/../", "/qc/other/"):
                with self.subTest(return_url=unsafe_url):
                    response = self.render_inline_disable(unsafe_url)
                    self.assertEqual(response["Location"], "/qc/admin/")
        finally:
            set_script_prefix(original_prefix)

    def test_shared_disable_get_never_changes_maintenance(self):
        with patch.object(maintenance, "disable") as disable:
            response = self.client.get(self.url, {
                "action": "disable", "generation": "4",
                "next": reverse("admin:index"), "return_to_page": "1",
            })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)
        disable.assert_not_called()

    def test_shared_disable_preserves_generation_and_busy_conflicts(self):
        for error in (
            maintenance.MaintenanceError("Maintenance state changed; reload this page."),
            maintenance.MaintenanceBusy("Another maintenance action is in progress. Retry shortly."),
        ):
            with (
                self.subTest(error=error),
                patch("qc_tool.database.transfers.service.validate_resume_database"),
                patch.object(maintenance, "disable", side_effect=error),
            ):
                response = self.client.post(self.url, {
                    "action": "disable", "generation": "4",
                    "next": reverse("admin:index"), "return_to_page": "1",
                })
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("Location", response)
            self.assertNotContains(response, "Maintenance mode disabled.", status_code=409)
            self.assertContains(response, str(error), status_code=409)

    @override_settings(MAINTENANCE_MODE=True)
    def test_shared_disable_cannot_bypass_deployment_enforcement(self):
        with (
            patch("qc_tool.database.transfers.service.validate_resume_database") as validate,
            patch.object(maintenance, "disable") as disable,
        ):
            response = self.client.post(self.url, {
                "action": "disable", "generation": "4",
                "next": reverse("admin:index"), "return_to_page": "1",
            })
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("Location", response)
        validate.assert_not_called()
        disable.assert_not_called()

    def test_shared_disable_requires_authentication_administrator_and_csrf(self):
        payload = {"action": "disable", "generation": "4",
                   "next": reverse("admin:index"), "return_to_page": "1"}
        anonymous = Client()
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.administrator)
        staff = get_user_model().objects.create_user(username="inline-maintenance-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        non_administrator = Client()
        non_administrator.force_login(staff)
        with patch.object(maintenance, "disable") as disable:
            response = anonymous.post(self.url, payload)
            self.assertRedirects(
                response, reverse("admin_login") + "?next=" + self.url,
                fetch_redirect_response=False,
            )
            self.assertEqual(protected.post(self.url, payload).status_code, 403)
            self.assertEqual(non_administrator.post(self.url, payload).status_code, 403)
        disable.assert_not_called()

    def render_status(self, phase):
        request = RequestFactory().get(self.url)
        request.user = self.administrator
        with patch.object(maintenance, "read_status", return_value=self.status(phase=phase)):
            return maintenance_control(request)

    def test_stopping_does_not_offer_disable_or_claim_readiness(self):
        response = self.render_status("stopping")

        self.assertContains(response, "Turning on maintenance")
        self.assertContains(response, "Changes are paused while QC jobs stop.")
        self.assertContains(response, 'data-maintenance-progress')
        self.assertContains(response, 'disabled aria-describedby="maintenance-stopping-note"')
        self.assertNotContains(response, "Check workers")

    def test_unreadable_state_does_not_offer_controls_or_claim_readiness(self):
        with patch.object(
            maintenance, "read_status",
            side_effect=maintenance.MaintenanceError("Maintenance state cannot be read. Contact the operator."),
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "Maintenance status unavailable", status_code=503)
        self.assertFalse(any(tag == "form" for tag, attributes in _MaintenanceControls(response).elements))

    def test_ready_offers_disable_without_technical_maintenance_panels(self):
        response = self.render_status("ready")

        self.assertContains(response, 'value="disable"')
        self.assertContains(response, "do not resume automatically")
        self.assertContains(response, "Turn off maintenance")
        self.assertNotContains(response, "Technical details")
        self.assertNotContains(response, "external database writers")
        self.assertNotContains(response, "Workers last checked")
        self.assertNotContains(response, "Recheck workers")
        self.assertNotContains(response, 'data-maintenance-progress')
        self.assertNotContains(response, 'value="advance"')

    def test_transfer_return_url_preserves_workflow_across_maintenance_action(self):
        return_url = reverse("admin_data_transfer") + "?operation=source-package&tab=import"
        request = RequestFactory().post(
            self.url,
            {"action": "advance", "generation": "1", "next": return_url},
        )
        request.user = self.administrator
        with (
            patch.object(maintenance, "read_status", return_value=self.status(phase="ready")),
            patch.object(maintenance, "advance") as advance,
        ):
            response = maintenance_control(request)

        self.assertEqual(response.status_code, 200)
        advance.assert_called_once_with(expected_generation=1)
        self.assertContains(response, "Continue to your task")
        self.assertContains(
            response,
            '<input type="hidden" name="next" value="{}">'.format(
                return_url.replace("&", "&amp;"),
            ),
            html=True,
        )
        self.assertNotIn("Location", response)

    def test_transfer_return_url_rejects_other_destinations(self):
        transfer_url = reverse("admin_data_transfer")
        invalid_urls = (
            "https://example.test" + transfer_url,
            "//example.test" + transfer_url,
            self.url,
            transfer_url + "#other",
            transfer_url + "?operation=" + "x" * 1024,
            transfer_url + "?operation=source\npackage",
            "/\\example.test" + transfer_url,
        )
        for return_url in invalid_urls:
            with self.subTest(return_url=return_url):
                request = RequestFactory().get(self.url, {"next": return_url})
                request.user = self.administrator
                with patch.object(
                    maintenance, "read_status", return_value=self.status(phase="ready"),
                ):
                    response = maintenance_control(request)
                self.assertEqual(_MaintenanceControls(response).named("next"), [])
                self.assertNotContains(response, "Continue to your task")

    def test_transfer_owner_replaces_maintenance_controls_with_transfer_link(self):
        operation_id = "a2b12963-17de-45d0-804e-f4c35b1c4d05"
        with patch(
            "qc_tool.frontend.dashboard.views.admin_maintenance.active_operation",
            return_value={"kind": "import", "operation_id": operation_id},
        ):
            response = self.render_status("ready")

        self.assertContains(response, "Changes are paused for a backup or restore.")
        self.assertContains(response, "View progress")
        self.assertContains(
            response, reverse("admin_data_transfer") + "?operation=" + operation_id,
        )
        self.assertEqual(_MaintenanceControls(response).named("action"), [])
        self.assertContains(response, 'disabled aria-describedby="maintenance-transfer-note"')
        self.assertContains(response, 'disabled aria-describedby="admin-maintenance-control-note"')

    @override_settings(MAINTENANCE_MODE=True)
    def test_deployment_override_cannot_be_disabled_from_ui(self):
        request = RequestFactory().post(
            self.url, {"action": "disable", "generation": "1"},
        )
        request.user = self.administrator
        with (
            patch.object(maintenance, "read_status", return_value=self.status(phase="ready")),
            patch.object(maintenance, "disable") as disable,
        ):
            response = maintenance_control(request)

        self.assertContains(
            response, "cannot be disabled here", status_code=409,
        )
        self.assertEqual(_MaintenanceControls(response).named("action"), [])
        disable.assert_not_called()
