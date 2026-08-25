"""Semantic contracts shared by normal and recovery browser pages."""

import re

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse


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
        self.assertTemplateUsed(
            response,
            "dashboard/includes/navigation.html",
        )
        self.assertTemplateUsed(response, "dashboard/footer.html")

        document = response.content.decode(response.charset)
        self.assertIn('<body class="qc-shell ', document)
        self.assertEqual(document.count('<header class="site-header">'), 1)
        self.assertEqual(document.count("<main"), 1)
        self.assertEqual(document.count('<footer class="footer">'), 1)
        skip_link = re.search(
            r'<a\s+class="skip-link"\s+href="#([^"]+)">',
            document,
        )
        self.assertIsNotNone(skip_link)
        self.assertIn('id="{}"'.format(skip_link.group(1)), document)
        self.assertIn('<nav id="menucontainer"', document)
        self.assertIn('aria-label="Primary navigation"', document)
        self.assertIn('<main id="main-content"', document)
        self.assertIn('tabindex="-1"', document)
        self.assertIn('id="section-footer"', document)

        logout_url = reverse("logout")
        self.assertEqual(
            document.count(
                '<form method="post" action="{}">'.format(logout_url)
            ),
            1,
        )
        self.assertNotIn('href="{}"'.format(logout_url), document)

        for asset_path in (
            "dashboard/css/ui/tokens.css",
            "dashboard/css/ui/shell.css",
        ):
            self.assertIsNotNone(finders.find(asset_path))
            self.assertEqual(document.count(static(asset_path)), 1)

        icon_sprite = "dashboard/icons/ui.svg"
        self.assertIsNotNone(finders.find(icon_sprite))
        self.assertIn(static(icon_sprite), document)

    def test_homepage_and_404_render_the_same_application_shell(self):
        homepage = self.client.get(reverse("deliveries"))
        missing_page = self.client.get("/missing-shared-shell-page/")

        self.assert_shared_shell(homepage, status_code=200)
        self.assert_shared_shell(missing_page, status_code=404)

        for response, status_code in (
            (homepage, 200),
            (missing_page, 404),
        ):
            self.assertContains(
                response,
                "https://github.com/eea/copernicus_quality_tools",
                status_code=status_code,
            )
            self.assertContains(
                response,
                "https://eea.github.io/copernicus_quality_tools/",
                status_code=status_code,
            )
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

        self.assertNotContains(
            homepage,
            "https://github.com/eea/copernicus_quality_tools/wiki",
        )
