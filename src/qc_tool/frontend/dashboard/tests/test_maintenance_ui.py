"""Maintenance retains browsing and presents native disabled write controls."""

from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.dashboard.context_processors import maintenance_context
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition


class Controls(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.fields = []
        self.forms = []
        self.fieldsets = []
        self.form = None
        self.feed(response.content.decode(response.charset))

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "form":
            self.form = attributes
            self.forms.append(attributes)
        if tag == "fieldset":
            self.fieldsets.append("disabled" in attributes)
        if tag in {"input", "button", "select", "textarea"}:
            self.fields.append((attributes, "disabled" in attributes or any(self.fieldsets), self.form))

    def handle_endtag(self, tag):
        if tag == "fieldset":
            self.fieldsets.pop()
        elif tag == "form":
            self.form = None


class MaintenancePresentationContextTests(SimpleTestCase):
    def test_context_uses_the_request_snapshot_without_database_or_storage_reads(self):
        request = RequestFactory().get("/deliveries/")
        request.maintenance_active = True
        request.maintenance_status = {"enabled": True, "phase": "ready"}

        context = maintenance_context(request)["maintenance"]

        self.assertTrue(context["enabled"])
        self.assertEqual(context["phase"], "ready")
        self.assertIn("browse and download", context["notice"])


class MaintenanceBrowsingPresentationTests(TestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=Path(temporary) / "maintenance",
            MAINTENANCE_MODE=False,
        ))
        self.administrator = get_user_model().objects.create_superuser(
            username="read-only-ui-admin", password="test-password",
        )
        managed_definition("example")
        self.client.force_login(self.administrator)
        self.status = maintenance.enable(self.administrator, 0)

    def test_shared_notice_is_visible_across_workspace_account_and_admin_pages(self):
        for phase in ("stopping", "ready"):
            if phase == "ready":
                maintenance.advance(self.status["generation"])
            for route in ("dashboard_home", "deliveries", "products", "account_settings", "admin:index"):
                with self.subTest(phase=phase, route=route):
                    response = self.client.get(reverse(route))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context["maintenance"]["phase"], phase)
                    if route == "admin:index":
                        notice = (
                            "Turning on maintenance. QC work is stopping."
                            if phase == "stopping" else
                            "Maintenance is on. You can browse and download existing data; changes are paused."
                        )
                    else:
                        notice = "You can browse and download existing data."
                    self.assertContains(response, notice)
                    self.assertContains(response, "data-maintenance-banner", count=1)
                    self.assertContains(response, 'name="qc-maintenance" content="on"')
                    self.assertContains(response, "dashboard/js/shared/maintenance.js", count=1)

    def test_upload_pages_remain_navigable_with_disabled_native_file_controls(self):
        for route in ("file_upload", "boundaries_upload", "product_upload"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                file_controls = [disabled for attributes, disabled, _form in Controls(response).fields if attributes.get("type") == "file"]
                self.assertTrue(file_controls)
                self.assertTrue(all(file_controls))

    def test_mutation_form_submits_are_disabled_but_review_filter_remains_usable(self):
        response = self.client.get(reverse("submission_queue"))
        self.assertEqual(response.status_code, 200)
        controls = Controls(response)
        filter_controls = [disabled for _attributes, disabled, form in controls.fields if form and form.get("method") == "get"]
        self.assertTrue(filter_controls)
        self.assertFalse(any(filter_controls))
        self.assertContains(response, 'href="' + reverse("products") + '"')

    def test_account_forms_disable_writes_without_hiding_information(self):
        response = self.client.get(reverse("account_settings"))
        self.assertEqual(response.status_code, 200)
        submits = [disabled for attributes, disabled, form in Controls(response).fields if form and form.get("method") == "post" and attributes.get("type") == "submit"]
        self.assertTrue(submits)
        self.assertTrue(all(submits))

    def test_operator_login_stays_enabled_with_an_explanation(self):
        for route in ("login", "admin_login"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                submits = [disabled for attributes, disabled, form in Controls(response).fields if form and "data-maintenance-exempt" in form and attributes.get("type") == "submit"]
                self.assertTrue(submits)
                self.assertFalse(any(submits))
                self.assertContains(response, "only administrators and product managers can sign in")

    def test_native_admin_save_is_disabled_and_maintenance_controls_are_exempt(self):
        response = self.client.get(reverse("admin:auth_user_change", args=(self.administrator.pk,)))
        self.assertEqual(response.status_code, 200)
        saves = [disabled for attributes, disabled, _form in Controls(response).fields if attributes.get("name") == "_save"]
        self.assertTrue(saves)
        self.assertTrue(all(saves))
        controls_response = self.client.get(reverse("admin_maintenance"))
        controls = Controls(controls_response)
        actions = {attributes.get("value"): disabled for attributes, disabled, form in controls.fields if attributes.get("name") == "action" and form and "data-maintenance-exempt" in form}
        # The controls bypass the generic read-only presentation, but resuming
        # still waits for the application's stopping barrier to complete.
        self.assertEqual(actions, {"disable": True, "progress": False})

        maintenance.advance(self.status["generation"])
        ready_controls = Controls(self.client.get(reverse("admin_maintenance")))
        ready_actions = [disabled for attributes, disabled, form in ready_controls.fields if attributes.get("name") == "action" and form and "data-maintenance-exempt" in form]
        self.assertEqual(ready_actions, [False])

    def test_returning_to_normal_mode_restores_native_upload_controls(self):
        ready = maintenance.advance(self.status["generation"])
        maintenance.disable(self.administrator, ready["generation"])

        response = self.client.get(reverse("file_upload"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="qc-maintenance" content="off"')
        self.assertFalse(any(disabled for attributes, disabled, _form in Controls(response).fields if attributes.get("type") == "file"))

    @override_settings(DEBUG=False)
    def test_maintenance_notice_does_not_echo_private_missing_route_details(self):
        marker = "private-lookup-detail-should-not-appear"

        response = self.client.get("/missing/{}/".format(marker))

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, marker, status_code=404)
        self.assertContains(response, 'href="" data-maintenance-reload', status_code=404)
