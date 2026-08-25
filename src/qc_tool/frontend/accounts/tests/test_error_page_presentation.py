"""Regression tests for the shared browser error-page presentation."""

from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


DOCUMENTATION_URL = "https://eea.github.io/copernicus_quality_tools/"
SUPPORT_URL = "https://github.com/eea/copernicus_quality_tools/issues"


class _ImageParser(HTMLParser):
    def __init__(self, target_src):
        super().__init__()
        self.target_src = target_src
        self.attributes = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "img" and attributes.get("src") == self.target_src:
            self.attributes = attributes


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ErrorPagePresentationTests(TestCase):
    """Keep the branded HTML recovery experience consistent and safe."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="error-page-user",
            password="test-password",
        )

    def assert_shared_error_page(
        self,
        response,
        *,
        status_code,
        image_name,
        homepage_available=True,
    ):
        self.assertEqual(response.status_code, status_code)
        self.assertContains(
            response,
            '<body class="qc-shell error-layout">',
            status_code=status_code,
        )
        self.assertContains(
            response,
            '<main id="main-content" class="site-main error-page" tabindex="-1">',
            status_code=status_code,
        )
        self.assertEqual(
            response.content.decode(response.charset).count("<main"),
            1,
        )
        self.assertContains(
            response,
            'class="error-hero"',
            status_code=status_code,
        )
        self.assertContains(
            response,
            'class="error-help"',
            status_code=status_code,
        )

        image_path = "accounts/img/{}".format(image_name)
        self.assertIsNotNone(finders.find(image_path))
        self.assertContains(
            response,
            'src="{}"'.format(static(image_path)),
            status_code=status_code,
        )
        image_parser = _ImageParser(static(image_path))
        image_parser.feed(response.content.decode(response.charset))
        self.assertIsNotNone(image_parser.attributes)
        self.assertEqual(image_parser.attributes["alt"], "")
        self.assertEqual(image_parser.attributes["width"], "1163")
        self.assertEqual(image_parser.attributes["height"], "943")

        if homepage_available:
            self.assertContains(
                response,
                'class="btn btn-primary error-primary-action"',
                status_code=status_code,
            )
            self.assertContains(response, "#home", status_code=status_code)
            self.assertContains(
                response,
                "Go to homepage",
                status_code=status_code,
            )
        else:
            self.assertNotContains(
                response,
                "error-primary-action",
                status_code=status_code,
            )
        self.assertContains(
            response,
            'class="btn error-secondary-action"',
            status_code=status_code,
        )
        back_fallback = (
            reverse("deliveries") if homepage_available else DOCUMENTATION_URL
        )
        self.assertContains(
            response,
            'href="{}"'.format(back_fallback),
            status_code=status_code,
        )
        self.assertContains(response, "data-error-back", status_code=status_code)
        self.assertContains(response, "#arrow-left", status_code=status_code)
        self.assertContains(response, "Go back", status_code=status_code)
        self.assertNotContains(
            response,
            "onclick=",
            status_code=status_code,
        )

        self.assertContains(
            response,
            'href="{}"'.format(DOCUMENTATION_URL),
            status_code=status_code,
        )
        self.assertContains(
            response,
            'href="{}"'.format(SUPPORT_URL),
            status_code=status_code,
        )
        self.assertContains(
            response,
            "Need help?",
            status_code=status_code,
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("Cookie", response["Vary"])

        for asset_path in (
            "accounts/css/errors/shell.css",
            "accounts/css/errors/hero.css",
            "accounts/css/errors/help.css",
            "accounts/css/errors/responsive.css",
            "accounts/js/error-page.js",
        ):
            self.assertIsNotNone(finders.find(asset_path))
            self.assertContains(
                response,
                static(asset_path),
                status_code=status_code,
            )

        shared_icon_sprite = "dashboard/icons/ui.svg"
        self.assertIsNotNone(finders.find(shared_icon_sprite))
        self.assertContains(
            response,
            static(shared_icon_sprite),
            status_code=status_code,
        )

    def test_anonymous_404_uses_status_artwork_and_recovery_layout(self):
        response = self.client.get("/missing-branded-error-page/")

        self.assertTemplateUsed(response, "accounts/errors/404.html")
        self.assert_shared_error_page(
            response,
            status_code=404,
            image_name="error-404.webp",
        )
        self.assertContains(
            response,
            "We couldn’t find that page",
            status_code=404,
        )
        self.assertNotContains(response, "error-403.webp", status_code=404)
        self.assertContains(
            response,
            'href="{}"'.format(reverse("login")),
            status_code=404,
        )
        self.assertNotContains(response, "Sign out (", status_code=404)
        self.assertEqual(
            response["X-Robots-Tag"],
            "noindex, nofollow, noarchive",
        )

    def test_authenticated_404_keeps_account_navigation(self):
        self.client.force_login(self.user)

        response = self.client.get("/missing-authenticated-error-page/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            'class="navbar-user-name"',
            status_code=404,
        )
        self.assertContains(
            response,
            'title="{}"'.format(self.user.username),
            status_code=404,
        )
        self.assertNotContains(
            response,
            'href="{}"'.format(reverse("login")),
            status_code=404,
        )

    def test_authenticated_403_uses_status_artwork_without_permission_leaks(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("boundaries"))

        self.assertTemplateUsed(response, "accounts/errors/403.html")
        self.assert_shared_error_page(
            response,
            status_code=403,
            image_name="error-403.webp",
        )
        self.assertContains(
            response,
            "You do not have access to this page",
            status_code=403,
        )
        self.assertNotContains(response, "error-404.webp", status_code=403)
        self.assertNotContains(
            response,
            "manage_configuration",
            status_code=403,
        )

    def test_403_without_homepage_permission_still_offers_safe_back_action(self):
        permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.VIEW_DELIVERIES.value,
        )
        for group in self.user.groups.all():
            group.permissions.remove(permission)
        self.user.user_permissions.remove(permission)
        self.client.force_login(self.user)

        response = self.client.get(reverse("boundaries"))

        self.assert_shared_error_page(
            response,
            status_code=403,
            image_name="error-403.webp",
            homepage_available=False,
        )
