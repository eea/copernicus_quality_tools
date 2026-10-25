"""Semantic contracts shared by normal and recovery browser pages."""

import re
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.services.role_permissions import capability_content_type


class _ShellMarkup(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.images = []
        self.anchors = []
        self.brands = []
        self.brand_text = []
        self.return_links = []
        self.menu = []
        self.menu_depth = 0
        self.feed(response.content.decode(response.charset))

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if self.menu_depth:
            self.menu.append(self.get_starttag_text())
            if tag == "ul":
                self.menu_depth += 1
        elif tag == "ul" and "main-menu" in attributes.get("class", "").split():
            self.menu_depth = 1
        if tag == "a":
            self.anchors.append(attributes)
            if "qc-brand" in attributes.get("class", "").split():
                self.brands.append(attributes)
            if "site-header__back" in attributes.get("class", "").split():
                self.return_links.append(attributes)
        elif tag == "img":
            self.images.append((attributes, self.anchors[-1] if self.anchors else {}))

    def handle_endtag(self, tag):
        if self.menu_depth:
            if tag == "ul":
                self.menu_depth -= 1
            if self.menu_depth:
                self.menu.append(f"</{tag}>")
        if tag == "a" and self.anchors:
            self.anchors.pop()

    def handle_data(self, text):
        if self.menu_depth:
            self.menu.append(text)
        if self.anchors and "qc-brand" in self.anchors[-1].get("class", "").split():
            self.brand_text.append(text)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class SharedApplicationShellTests(TestCase):
    """Guard shell reuse without coupling tests to pixel values."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="shared-shell-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def assert_shared_shell(self, response, *, status_code):
        self.assertEqual(response.status_code, status_code)
        self.assertTemplateUsed(response, "dashboard/shared/header.html")
        self.assertTemplateUsed(response, "dashboard/shared/brand.html")
        self.assertTemplateUsed(
            response,
            "dashboard/shared/navigation.html",
        )
        self.assertTemplateUsed(response, "dashboard/shared/footer.html")

        document = response.content.decode(response.charset)
        self.assertIn('<body class="qc-shell ', document)
        self.assertEqual(
            len(re.findall(r'<header\b[^>]*\bclass="[^"]*\bsite-header\b[^"]*"', document)),
            1,
        )
        self.assertEqual(document.count("<main"), 1)
        self.assertEqual(document.count('<footer class="footer">'), 1)
        skip_link = re.search(
            r'<a\s+class="skip-link"\s+href="#([^"]+)">',
            document,
        )
        self.assertIsNotNone(skip_link)
        self.assertIn('id="{}"'.format(skip_link.group(1)), document)
        self.assertIn('<div id="menucontainer"', document)
        self.assertIn('aria-label="Primary navigation"', document)
        toggle = re.search(r'<button\b[^>]*\bdata-header-toggle\b[^>]*>', document)
        self.assertIsNotNone(toggle, "The shared header needs a mobile navigation control.")
        self.assertIn('type="button"', toggle.group(0))
        self.assertIn('aria-controls="primary-navigation-menu"', toggle.group(0))
        self.assertIn('aria-expanded="false"', toggle.group(0))
        self.assertIn('id="primary-navigation-menu"', document)
        self.assertIn('<main id="main-content"', document)
        self.assertIn('tabindex="-1"', document)
        self.assertIn('id="section-footer"', document)

        logout_url = reverse("logout")
        self.assertEqual(
            document.count(
                '<form method="post" action="{}" data-maintenance-write>'.format(logout_url)
            ),
            1,
        )
        self.assertNotIn('href="{}"'.format(logout_url), document)

        for asset_path in (
            "dashboard/css/ui/tokens.css",
            "dashboard/css/ui/shell.css",
            "dashboard/css/ui/header.css",
            "dashboard/css/ui/actions.css",
            "dashboard/js/shared/navigation.js",
        ):
            self.assertIsNotNone(finders.find(asset_path))
            self.assertEqual(document.count(static(asset_path)), 1)

        icon_sprite = "dashboard/icons/ui.svg"
        self.assertIsNotNone(finders.find(icon_sprite))
        self.assertIn(static(icon_sprite), document)

    def primary_menu(self, response):
        menu = "".join(_ShellMarkup(response).menu)
        self.assertTrue(menu, "The page needs the shared primary menu.")
        return menu

    def test_homepage_and_404_render_the_same_application_shell(self):
        homepage = self.client.get(reverse("dashboard_home"))
        missing_page = self.client.get("/missing-shared-shell-page/")

        self.assert_shared_shell(homepage, status_code=200)
        self.assert_shared_shell(missing_page, status_code=404)

        for response, status_code in ((homepage, 200), (missing_page, 404)):
            self.assertContains(
                response,
                'aria-label="Copernicus website"',
                status_code=status_code,
            )
            self.assertContains(
                response,
                'aria-label="European Environment Agency website"',
                status_code=status_code,
            )

    def test_workspace_and_public_api_logos_use_the_shared_dashboard_brand_link(self):
        responses = [
            ("workspace", self.client.get(reverse("dashboard_home"))),
            ("authenticated API", self.client.get(reverse("api_homepage"))),
        ]
        self.client.logout()
        responses.append(("public API", self.client.get(reverse("api_homepage"))))

        for page, response in responses:
            with self.subTest(page=page):
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "dashboard/shared/header.html")
                self.assertTemplateUsed(response, "dashboard/shared/brand.html")
                markup = _ShellMarkup(response)
                images = markup.images
                brand_label = " ".join(" ".join(markup.brand_text).split())
                if page == "workspace":
                    self.assertEqual(brand_label, "CLMS QC Tool")
                    self.assertEqual(markup.return_links, [])
                else:
                    self.assertEqual(brand_label, "CLMS QC Tool | API")
                    self.assertEqual(len(markup.return_links), 1)
                    back = markup.return_links[0]
                    self.assertEqual(back.get("href"), reverse("dashboard_home"))
                    self.assertEqual(back.get("aria-label"), "Back to workspace")
                    self.assertEqual(back.get("title"), "Back to workspace")
                    self.assertTrue({"btn-qc-secondary", "btn-qc-icon"}.issubset(back.get("class", "").split()))
                    self.assertContains(response, static("dashboard/icons/ui.svg") + "#arrow-left")
                for filename in ("logo_copernicus_big.png", "logo_land_monitoring_medium.png"):
                    with self.subTest(logo=filename):
                        matching = [
                            (image, anchor) for image, anchor in images
                            if image.get("src") == static("dashboard/img/" + filename)
                        ]
                        self.assertEqual(len(matching), 1)
                        _image, anchor = matching[0]
                        self.assertEqual(anchor.get("href"), reverse("dashboard_home"))
                        self.assertIn("qc-brand", anchor.get("class", "").split())

    def test_authenticated_api_reuses_workspace_navigation_and_action_components(self):
        response = self.client.get(reverse("api_homepage"))

        self.assert_shared_shell(response, status_code=200)
        self.assertTemplateUsed(response, "dashboard/shared/profile_menu.html")
        menu = self.primary_menu(response)
        self.assertIn('id="profile-menu-button"', menu)
        self.assertIn('action="{}"'.format(reverse("logout")), menu)

    def test_authenticated_header_has_announcement_docs_and_profile_actions(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        menu = self.primary_menu(response)
        self.assertIn('href="{}"'.format(reverse("announcement")), menu)
        self.assertIn(
            'href="https://github.com/eea/copernicus_quality_tools/wiki"',
            menu,
        )
        self.assertIn('id="profile-menu-button"', menu)
        self.assertIn('aria-controls="profile-menu"', menu)
        profile = re.search(r'<details\b[^>]*\bdata-header-menu[^>]*>(.*?)</details>', menu, re.DOTALL)
        self.assertIsNotNone(profile, "The shared Profile menu must work without JavaScript.")
        self.assertRegex(profile.group(1), r'<summary\b[^>]*\bid="profile-menu-button"')
        self.assertNotIn('data-toggle="dropdown"', profile.group(1))
        self.assertIn("Profile", menu)
        self.assertIn(
            'href="{}"'.format(reverse("account_settings")),
            menu,
        )
        self.assertIn("Settings", menu)
        self.assertEqual(
            menu.count(
                '<form method="post" action="{}" data-maintenance-write>'.format(reverse("logout"))
            ),
            1,
        )
        self.assertIn('name="csrfmiddlewaretoken"', menu)
        self.assertIn("Log out", menu)
        self.assertNotIn('href="{}"'.format(reverse("login")), menu)
        self.assertNotIn("Sign in", menu)
        self.assertEqual(
            re.findall(r'<a\b[^>]*\bhref="([^"]+)"', menu),
            [
                reverse("announcement"),
                "https://github.com/eea/copernicus_quality_tools/wiki",
                reverse("account_settings"),
            ],
        )

    def test_shared_header_preserves_account_and_recovery_brand_destinations(self):
        documentation_url = "https://github.com/eea/copernicus_quality_tools/wiki"

        def assert_destination(response, expected, *, status=200):
            self.assertEqual(response.status_code, status)
            self.assertTemplateUsed(response, "dashboard/shared/header.html")
            brands = _ShellMarkup(response).brands
            self.assertEqual(len(brands), 1)
            self.assertEqual(brands[0].get("href"), expected)

        assert_destination(
            self.client.get(reverse("change_password")),
            reverse("account_settings"),
        )
        assert_destination(
            self.client.post(reverse("api_token_create"), {
                "name": "Shared header test",
                "current_password": "test-password",
            }),
            reverse("account_settings"),
        )

        # Direct grants exercise accounts without the default workspace role.
        self.user.groups.through.objects.filter(user_id=self.user.pk).delete()
        self.user.user_permissions.through.objects.filter(user_id=self.user.pk).delete()
        self.user.user_permissions.add(Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.CHANGE_PASSWORD.value,
        ))
        assert_destination(self.client.get(reverse("change_password")), documentation_url)

        self.user.user_permissions.add(Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.MANAGE_OWN_ACCOUNT.value,
        ))
        assert_destination(self.client.get(reverse("account_settings")), documentation_url)
        assert_destination(
            self.client.get(reverse("change_password")),
            reverse("account_settings"),
        )
        assert_destination(
            self.client.get("/missing-restricted-shared-header-page/"),
            documentation_url,
            status=404,
        )

    def test_anonymous_header_has_only_documentation_and_sign_in(self):
        self.client.logout()

        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        menu = self.primary_menu(response)
        self.assertIn(
            'href="https://github.com/eea/copernicus_quality_tools/wiki"',
            menu,
        )
        self.assertIn('href="{}"'.format(reverse("login")), menu)
        self.assertIn("Sign in", menu)
        self.assertEqual(
            re.findall(r'<a\b[^>]*\bhref="([^"]+)"', menu),
            [
                "https://github.com/eea/copernicus_quality_tools/wiki",
                reverse("login"),
            ],
        )
        for authenticated_control in (
            'href="{}"'.format(reverse("announcement")),
            'href="{}"'.format(reverse("account_settings")),
            'action="{}"'.format(reverse("logout")),
            'id="profile-menu-button"',
            "Profile",
            "Settings",
            "Log out",
        ):
            with self.subTest(authenticated_control=authenticated_control):
                self.assertNotIn(authenticated_control, menu)
