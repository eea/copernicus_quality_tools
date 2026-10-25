"""Every Admin page exposes the current pause and a safe way to resume."""

from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import get_script_prefix, reverse, set_script_prefix

from qc_tool.frontend.dashboard.services import maintenance


class _Markup(HTMLParser):
    """Retain element ancestry so the mobile menu cannot hide the status."""

    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, response):
        super().__init__()
        self.elements = []
        self.stack = []
        self.feed(response.content.decode(response.charset))

    def handle_starttag(self, tag, attributes):
        element = {
            "tag": tag, "attributes": dict(attributes),
            "ancestors": tuple(self.stack), "text": [],
        }
        self.elements.append(element)
        if tag not in self.void_tags:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, value):
        for element in self.stack:
            element["text"].append(value)

    def descendants(self, parent, tag=None):
        return [element for element in self.elements
                if any(ancestor is parent for ancestor in element["ancestors"])
                and (tag is None or element["tag"] == tag)]

    def marked(self, attribute):
        return [element for element in self.elements if attribute in element["attributes"]]


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class AdminMaintenanceBannerTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
        ))
        self.administrator = get_user_model().objects.create_superuser(
            username="banner-administrator", password="test-password",
        )
        self.client.force_login(self.administrator)

    def enable(self, *, ready=False):
        status = maintenance.enable(self.administrator, expected_generation=0)
        return maintenance.advance(status["generation"]) if ready else status

    def banner(self, response):
        markup = _Markup(response)
        banners = markup.marked("data-maintenance-banner")
        self.assertEqual(len(banners), 1)
        banner = banners[0]
        self.assertIn("data-maintenance-admin", banner["attributes"])
        self.assertEqual(banner["attributes"].get("role"), "status")
        self.assertEqual(banner["attributes"].get("aria-live"), "polite")
        return markup, banner

    def off_form(self, markup, banner):
        forms = [element for element in markup.descendants(banner, "form")
                 if "data-maintenance-disable-form" in element["attributes"]]
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form["attributes"].get("method"), "post")
        self.assertEqual(form["attributes"].get("action"), reverse("admin_maintenance"))
        self.assertIn("data-maintenance-exempt", form["attributes"])
        fields = {element["attributes"]["name"]: element["attributes"].get("value", "")
                  for element in markup.descendants(form, "input")
                  if "name" in element["attributes"]}
        self.assertTrue(fields.get("csrfmiddlewaretoken"))
        self.assertEqual(fields.get("action"), "disable")
        self.assertEqual(fields.get("return_to_page"), "1")
        submits = [element for element in markup.descendants(form, "button")
                   if element["attributes"].get("type") == "submit"]
        self.assertEqual(len(submits), 1)
        self.assertEqual(" ".join(submits[0]["text"]).strip(), "Turn off maintenance")
        return fields, submits[0]

    def test_ready_status_and_direct_off_control_are_shared_by_every_admin_area(self):
        status = self.enable(ready=True)
        for route in (
            "admin:index", "admin_user_management", "admin:auth_user_add",
            "boundaries", "admin_notifications", "admin_database", "admin_storage",
            "admin_data_transfer", "admin_maintenance", "admin:auth_group_changelist",
            "admin_backup_export", "admin_backup_import",
        ):
            with self.subTest(route=route):
                url = reverse(route)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                markup, banner = self.banner(response)
                self.assertNotIn("hidden", banner["attributes"])
                self.assertIn("Maintenance is on", " ".join(banner["text"]))
                self.assertIn("Creating users, editing records and other changes are paused.",
                              " ".join(banner["text"]))
                self.assertIn("Browsing and downloads remain available.", " ".join(banner["text"]))
                fields, submit = self.off_form(markup, banner)
                self.assertEqual(fields["generation"], str(status["generation"]))
                self.assertEqual(fields["next"], url)
                self.assertNotIn("disabled", submit["attributes"])
                headers = [element for element in markup.elements
                           if element["tag"] == "header" and element["attributes"].get("id") == "header"]
                self.assertEqual(len(headers), 1)
                self.assertLess(markup.elements.index(banner), markup.elements.index(headers[0]))
                self.assertEqual(banner["ancestors"], headers[0]["ancestors"])
                self.assertFalse(any(element["attributes"].get("id") == "primary-navigation-menu"
                                     for element in banner["ancestors"]))

    def test_return_destination_preserves_the_current_admin_query(self):
        self.enable(ready=True)
        for url in (
            reverse("admin:auth_user_changelist") + "?q=banner&is_active__exact=1",
            reverse("admin_backup_export") + "?components_selected=true&components=boundaries",
            reverse("admin_backup_import") + "?from=backups",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                markup, banner = self.banner(response)
                fields, _submit = self.off_form(markup, banner)

                self.assertEqual(fields["next"], url)

    def test_stopping_status_explains_why_resuming_is_not_yet_available(self):
        self.enable()

        markup, banner = self.banner(self.client.get(reverse("admin_user_management")))
        _fields, submit = self.off_form(markup, banner)

        self.assertIn("Turning on maintenance", " ".join(banner["text"]))
        self.assertIn("disabled", submit["attributes"])
        self.assertTrue(any(element["attributes"].get("href") == reverse("admin_maintenance")
                            for element in markup.descendants(banner, "a")))
        self.assertIn("QC work", " ".join(banner["text"]))

    def test_read_only_staff_sees_the_status_without_a_resume_control(self):
        staff = get_user_model().objects.create_user(username="banner-read-only-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        self.client.force_login(staff)
        self.enable(ready=True)

        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        markup, banner = self.banner(response)

        self.assertNotIn("hidden", banner["attributes"])
        self.assertIn("Maintenance is on", " ".join(banner["text"]))
        self.assertFalse(markup.descendants(banner, "form"))

    def test_admin_not_found_recovery_keeps_the_direct_resume_control(self):
        self.enable(ready=True)
        destination = reverse("admin:index") + "missing-banner-page/"

        response = self.client.get(destination)

        self.assertEqual(response.status_code, 404)
        markup, banner = self.banner(response)
        fields, submit = self.off_form(markup, banner)
        self.assertEqual(fields["next"], destination)
        self.assertNotIn("disabled", submit["attributes"])

    def test_login_status_does_not_offer_an_unauthenticated_resume_control(self):
        self.enable(ready=True)
        self.client.logout()

        markup, banner = self.banner(self.client.get(reverse("admin_login")))

        self.assertNotIn("hidden", banner["attributes"])
        self.assertFalse(markup.descendants(banner, "form"))

    def test_normal_mode_does_not_display_an_active_pause(self):
        markup, banner = self.banner(self.client.get(reverse("admin_user_management")))

        self.assertIn("hidden", banner["attributes"])
        for form in markup.descendants(banner, "form"):
            submits = [element for element in markup.descendants(form, "button")
                       if element["attributes"].get("type") == "submit"]
            self.assertTrue(all("disabled" in submit["attributes"] for submit in submits))

    def test_deployment_enforced_maintenance_cannot_offer_a_working_off_control(self):
        self.enable(ready=True)
        with override_settings(MAINTENANCE_MODE=True):
            markup, banner = self.banner(self.client.get(reverse("admin_user_management")))
        _fields, submit = self.off_form(markup, banner)

        self.assertIn("disabled", submit["attributes"])
        self.assertIn("deployment", " ".join(banner["text"]).lower())

    def test_unavailable_status_keeps_the_pause_visible_and_resuming_disabled(self):
        status = {**maintenance.read_status(), "enabled": True, "phase": "unavailable"}
        with patch("qc_tool.frontend.dashboard.middleware.read_status", return_value=status):
            markup, banner = self.banner(self.client.get(reverse("admin_user_management")))
        _fields, submit = self.off_form(markup, banner)

        self.assertNotIn("hidden", banner["attributes"])
        self.assertIn("Maintenance status unavailable", " ".join(banner["text"]))
        self.assertIn("disabled", submit["attributes"])

    def test_prefixed_admin_pages_keep_the_form_and_return_destination_inside_admin(self):
        self.enable(ready=True)
        previous_prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, previous_prefix)
        set_script_prefix("/quality/")

        for route in ("admin_user_management", "admin_backup_export", "admin_backup_import"):
            with self.subTest(route=route):
                destination = reverse(route) + "?q=banner"
                path_info = destination.removeprefix("/quality")
                response = self.client.get(path_info, SCRIPT_NAME="/quality")
                self.assertEqual(response.status_code, 200)
                markup, banner = self.banner(response)
                fields, _submit = self.off_form(markup, banner)

                self.assertEqual(fields["next"], destination)
