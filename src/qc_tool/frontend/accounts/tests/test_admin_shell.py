"""Admin authentication and recovery pages stay inside administration."""

import re
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory, TestCase, override_settings
from django.templatetags.static import static
from django.urls import get_script_prefix, reverse, set_script_prefix

from qc_tool.frontend.accounts.authentication.maintenance import cookie_session
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.users import provision_user
from qc_tool.frontend.accounts.views.errors import page_not_found, permission_denied
from qc_tool.frontend.dashboard.services import maintenance


class _Links(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.hrefs = []
        self.links = []
        self.elements = []
        self.text = []
        self.feed(response if isinstance(response, str) else response.content.decode())

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        self.elements.append((tag, attributes))
        if tag == "a":
            href = attributes.get("href")
            if href:
                self.hrefs.append(href)
                self.links.append(attributes)

    def handle_data(self, text):
        if text.strip():
            self.text.append(text.strip())


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class AdminShellTests(TestCase):
    password = "admin-shell-test-password"

    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
        ))
        self.administrator = provision_user(
            username="shell-administrator", password=self.password,
            groups=(Role.ADMIN.value,),
        ).user
        self.manager = provision_user(
            username="shell-manager", password=self.password,
            groups=(Role.PRODUCT_MANAGER.value,),
        ).user
        self.viewer = provision_user(username="shell-viewer", password=self.password).user

    def assert_admin_links(self, response, *, prefix=""):
        links = _Links(response).links
        self.assertTrue(links)
        workspace_links = []
        for link in links:
            href = link["href"]
            with self.subTest(href=href):
                if "qc-admin-workspace-link" in link.get("class", "").split():
                    self.assertEqual(href, prefix + "/")
                    workspace_links.append(link)
                    continue
                parsed = urlsplit(href)
                if not parsed.path and not parsed.scheme and not parsed.netloc:
                    continue  # Sorting, filters and fragments stay on this page.
                if parsed.scheme or parsed.netloc:
                    self.assertEqual(parsed.scheme, "https")
                    self.assertEqual(parsed.netloc, "eea.github.io")
                    self.assertTrue(parsed.path.startswith("/copernicus_quality_tools/"))
                    continue
                self.assertTrue(
                    href.startswith(prefix + "/admin/") or href.startswith("#"),
                    f"Admin page links outside administration: {href}",
                )
        self.assertLessEqual(len(workspace_links), 1)

    def admin_header(self, response):
        header = re.search(
            r'<header\b[^>]*\bid="header"[^>]*>(.*?)</header>',
            response.content.decode(), re.DOTALL,
        )
        self.assertIsNotNone(header, "Admin pages need their header landmark.")
        return header.group(1)

    def admin_navigation(self, response):
        navigation = re.search(r'<nav\b[^>]*aria-label="Administration"[^>]*>(.*?)</nav>',
                               self.admin_header(response), re.DOTALL)
        self.assertIsNotNone(navigation)
        return _Links(navigation.group(1))

    def test_administrator_header_has_exactly_four_task_sections(self):
        self.client.force_login(self.administrator)
        expected = ("admin:index", "admin_user_management", "admin_data_transfer", "admin_storage")
        for route in (*expected, "admin_maintenance", "admin:auth_user_changelist"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                navigation = self.admin_navigation(response)
                self.assertEqual(navigation.text, ["Overview", "User management", "Database", "Storage"])
                self.assertEqual(navigation.hrefs, [reverse(item) for item in expected])

    def test_header_marks_only_the_section_owning_the_current_task(self):
        self.client.force_login(self.administrator)
        cases = (
            (reverse("admin:index"), "admin:index"),
            (reverse("admin_user_management"), "admin_user_management"),
            (reverse("admin:auth_user_changelist"), "admin_user_management"),
            (reverse("admin:auth_group_changelist"), "admin_user_management"),
            (reverse("admin_database_records", args=["auth_permission"]), "admin_user_management"),
            (reverse("admin_data_transfer") + "?section=users&tab=import", "admin_data_transfer"),
            (reverse("admin_data_transfer") + "?section=users&tab=export", "admin_data_transfer"),
            (reverse("admin_data_transfer"), "admin_data_transfer"),
            (reverse("admin_database_records", args=["execution_job"]), "admin_data_transfer"),
            (reverse("admin_maintenance"), "admin_data_transfer"),
            (reverse("admin_storage"), "admin_storage"),
        )
        for url, owner in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                active = [link["href"] for link in self.admin_navigation(response).links
                          if link.get("aria-current") == "page"]
                self.assertEqual(active, [reverse(owner)])

    def test_admin_pages_start_with_an_accessible_return_button_and_plain_title(self):
        self.client.force_login(self.administrator)
        for route in (
            "admin:index", "admin_login", "admin:auth_user_changelist",
            "admin_user_management", "admin_data_transfer", "admin_maintenance", "admin_storage",
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateNotUsed(response, "dashboard/shared/brand.html")
                header = _Links(self.admin_header(response))
                self.assertEqual([tag for tag, _ in header.elements if tag == "img"], [])
                self.assertIn("CLMS QC Tool | Admin", " ".join(header.text))
                self.assertNotContains(response, 'id="user-tools"')
                self.assertContains(response, f'href="{static("dashboard/css/ui/actions.css")}"')
                links = [
                    link for link in header.links
                    if "qc-admin-workspace-link" in link.get("class", "").split()
                ]
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0]["href"], reverse("dashboard_home"))
                self.assertEqual(header.links[0], links[0])
                self.assertEqual(links[0].get("aria-label"), "Back to workspace")
                self.assertEqual(links[0].get("title"), "Back to workspace")
                self.assertTrue({"btn-qc-icon", "btn-qc-secondary"}.issubset(links[0].get("class", "").split()))
                self.assertIn(static("dashboard/icons/ui.svg") + "#arrow-left", self.admin_header(response))
                self.assert_admin_links(response)

    def test_workspace_keeps_its_shared_brand_and_both_logos(self):
        self.client.force_login(self.administrator)
        workspace = self.client.get(reverse("dashboard_home"))
        self.assertEqual(workspace.status_code, 200)
        self.assertTemplateUsed(workspace, "dashboard/shared/brand.html")
        for image in ("logo_copernicus_big.png", "logo_land_monitoring_medium.png"):
            self.assertContains(workspace, f'src="{static("dashboard/img/" + image)}"')

    def test_admin_profile_menu_keeps_identity_and_csrf_protected_account_actions(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:index"))
        header = self.admin_header(response)
        navigation = re.search(r'<nav\b[^>]*aria-label="Account"[^>]*>(.*?)</nav>', header, re.DOTALL)
        self.assertIsNotNone(navigation)
        account_menu = navigation.group(1)
        self.assertIn('class="nav navbar-nav navbar-right main-menu"', account_menu)
        details = re.search(r'<details\b[^>]*>(.*?)</details>', account_menu, re.DOTALL)
        self.assertIsNotNone(details, "The Profile menu must work without JavaScript.")
        self.assertIn("Profile", details.group(1))
        self.assertIn(self.administrator.username, details.group(1))
        self.assertEqual(header.count(self.administrator.username), 1)
        markup = _Links(details.group(1))
        self.assertEqual(markup.hrefs, [reverse("admin:password_change")])
        forms = [attributes for tag, attributes in markup.elements if tag == "form"]
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0].get("id"), "admin-logout-form")
        self.assertEqual(forms[0].get("method"), "post")
        self.assertEqual(forms[0].get("action"), reverse("admin:logout"))
        self.assertIn("data-maintenance-write", forms[0])
        self.assertIn('name="csrfmiddlewaretoken"', details.group(1))
        self.assertIn("Log out", details.group(1))
        self.assertIn('class="theme-toggle"', account_menu)
        self.assertRegex(account_menu, r'<li\b[^>]*>\s*<button class="theme-toggle"')
        self.assertNotContains(response, f'href="{reverse("admin:logout")}"')

    def test_admin_login_uses_admin_shell_and_preserves_internal_next(self):
        destination = reverse("admin_data_transfer")
        response = self.client.get(reverse("admin_login"), {"next": destination})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/qc_tool_login.html")
        self.assertContains(response, "Sign in to administration")
        self.assertContains(response, "data-maintenance-exempt")
        self.assertContains(response, f'name="next" value="{destination}"')
        self.assert_admin_links(response)

    def test_logout_returns_to_admin_login_and_removes_authentication(self):
        self.client.force_login(self.administrator)
        self.assertEqual(reverse("admin:logout"), reverse("admin_logout"))

        response = self.client.post(reverse("admin:logout"))

        self.assertRedirects(response, reverse("admin_login"), fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assert_admin_links(self.client.get(response.url))

    def test_logout_ignores_next_overrides_and_always_returns_to_admin_login(self):
        for destination in ("/", reverse("products"), "https://example.invalid/admin/"):
            for source in ("post", "query"):
                with self.subTest(destination=destination, source=source):
                    self.client.force_login(self.administrator)
                    url = reverse("admin_logout")
                    payload = {"next": destination} if source == "post" else {}
                    if source == "query":
                        url += "?" + urlencode({"next": destination})
                    response = self.client.post(url, payload)
                    self.assertRedirects(response, reverse("admin_login"), fetch_redirect_response=False)
                    self.assertNotIn(SESSION_KEY, self.client.session)

    def test_anonymous_custom_admin_routes_redirect_to_admin_login(self):
        for route in ("admin_user_management", "admin_maintenance", "admin_data_transfer", "admin_storage", "admin_logout"):
            with self.subTest(route=route):
                destination = reverse(route)
                response = self.client.get(destination)
                self.assertEqual(response.status_code, 302)
                redirect = urlsplit(response.url)
                self.assertEqual(redirect.path, reverse("admin_login"))
                self.assertEqual(parse_qs(redirect.query).get("next"), [destination])

    def test_admin_login_rejects_workspace_and_ambiguous_next_destinations(self):
        for destination in (
            "/", reverse("products"), "http://testserver/", "https://example.invalid/admin/",
            "/admin/../", "/admin/%2e%2e/", "/admin/%2f../", "/admin/%5c../",
        ):
            with self.subTest(destination=destination):
                client = Client()
                page = client.get(reverse("admin_login"), {"next": destination})
                self.assertContains(page, 'name="next" value=""')
                response = client.post(reverse("admin_login"), {
                    "username": self.administrator.username,
                    "password": self.password,
                    "next": destination,
                })
                self.assertRedirects(response, reverse("admin:index"), fetch_redirect_response=False)

    def test_admin_login_preserves_admin_next_after_authentication(self):
        destination = reverse("admin_data_transfer") + "?tab=history"
        response = self.client.post(reverse("admin_login"), {
            "username": self.administrator.username,
            "password": self.password,
            "next": destination,
        })
        self.assertRedirects(response, destination, fetch_redirect_response=False)

    def test_prefixed_admin_login_next_stays_within_prefixed_admin(self):
        original_prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, original_prefix)
        set_script_prefix("/qc-tool/")
        for destination, expected in (
            (reverse("admin_data_transfer"), reverse("admin_data_transfer")),
            ("/qc-tool/", reverse("admin:index")),
            ("/admin/data-transfer/", reverse("admin:index")),
        ):
            with self.subTest(destination=destination):
                response = Client().post("/admin/login/", {
                    "username": self.administrator.username,
                    "password": self.password,
                    "next": destination,
                }, SCRIPT_NAME="/qc-tool")
                self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_logout_rejects_get_and_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.get(reverse("admin_logout")).status_code, 405)
        self.assertEqual(client.post(reverse("admin_logout")).status_code, 403)
        self.assertIn(SESSION_KEY, client.session)

    def test_admin_not_found_uses_admin_recovery(self):
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:index") + "missing-page/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "admin/qc_tool_error.html")
        self.assertContains(response, "Return to administration", status_code=404)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertIn("no-store", response["Cache-Control"])
        self.assert_admin_links(response)

    def test_admin_denial_uses_admin_recovery_without_granting_manager_access(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("admin_maintenance"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "admin/qc_tool_error.html")
        self.assert_admin_links(response)

    def test_prefixed_admin_errors_keep_prefixed_admin_destinations(self):
        original_prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, original_prefix)
        for handler, status in ((permission_denied, 403), (page_not_found, 404)):
            for use_script_prefix in (False, True):
                with self.subTest(status=status, use_script_prefix=use_script_prefix):
                    set_script_prefix("/qc-tool/" if use_script_prefix else "/")
                    request = RequestFactory().get("/admin/missing/", SCRIPT_NAME="/qc-tool")
                    request.user = AnonymousUser()
                    response = handler(request, Exception("private lookup detail"))
                    self.assertEqual(response.status_code, status)
                    self.assertNotIn(b"private lookup detail", response.content)
                    self.assert_admin_links(response, prefix="/qc-tool" if use_script_prefix else "")

    def test_prefixed_login_links_remain_in_admin(self):
        original_prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, original_prefix)
        # WSGI sets the script prefix before URL reversing. TestClient does
        # not perform that WSGI setup from SCRIPT_NAME alone.
        set_script_prefix("/qc-tool/")
        response = self.client.get("/admin/login/", SCRIPT_NAME="/qc-tool")
        self.assertEqual(response.status_code, 200)
        self.assert_admin_links(response, prefix="/qc-tool")

    def test_workspace_recovery_keeps_existing_template(self):
        response = self.client.get("/missing-workspace-page/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "accounts/errors/404.html")

    def test_maintenance_login_keeps_operator_roles_and_csrf_protection(self):
        maintenance.enable("isolated admin shell test", 0)
        for user, allowed in ((self.administrator, True), (self.manager, True), (self.viewer, False)):
            with self.subTest(username=user.username):
                client = Client(enforce_csrf_checks=True)
                page = client.get(reverse("admin_login"))
                self.assertContains(page, "only administrators and product managers can sign in")
                self.assert_admin_links(page)
                token = str(page.context["csrf_token"])
                response = client.post(reverse("admin_login"), {
                    "username": user.username, "password": self.password,
                    "next": reverse("admin:index"),
                }, HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code, 302 if allowed else 200)
                if allowed:
                    self.assertEqual(response.url, reverse("admin:index"))
                self.assertEqual(SESSION_KEY in cookie_session(client.cookies[settings.SESSION_COOKIE_NAME].value), allowed)
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("admin_login"))
        self.assertEqual(client.post(reverse("admin_login"), {
            "username": self.administrator.username, "password": self.password,
        }).status_code, 403)

    def test_maintenance_still_blocks_logout_database_changes(self):
        self.client.force_login(self.administrator)
        maintenance.enable("isolated admin shell test", 0)
        response = self.client.post(reverse("admin_logout"))
        self.assertEqual(response.status_code, 503)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assert_admin_links(response)
