"""Deployment validation must understand the actual CSRF middleware in use."""

from io import StringIO

from django.conf import settings
from django.core.checks import Tags, run_checks
from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.middleware.csrf import CsrfViewMiddleware
from django.test import SimpleTestCase, override_settings

from qc_tool.frontend.dashboard.access.routes.csrf import UploadAwareCsrfViewMiddleware


# Do not import the check module here: the negative command tests must prove
# AppConfig.ready registered it, rather than registering it during discovery.
CSRF_MIDDLEWARE = tuple(
    f"{middleware.__module__}.{middleware.__name__}"
    for middleware in (CsrfViewMiddleware, UploadAwareCsrfViewMiddleware)
)


@override_settings(
    DEBUG=False,
    SECRET_KEY="ci-test-only-3xJw7pL9vK2qN8mR5tY1uB6cD4eF0gHsZa-DoNotDeploy",
    ALLOWED_HOSTS=["qc-tool.example.test"],
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    CSRF_USE_SESSIONS=False,
    SECURE_SSL_REDIRECT=True,
    SECURE_HSTS_SECONDS=31536000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
)
class CsrfDeploymentChecksTests(SimpleTestCase):
    def run_deployment_check(self):
        call_command("check", deploy=True, fail_level="WARNING", stdout=StringIO(), stderr=StringIO())

    def messages(self):
        return run_checks(tags=[Tags.security], include_deployment_checks=True)

    def test_actual_upload_aware_configuration_passes_strict_deployment_checks(self):
        self.assertIn(CSRF_MIDDLEWARE[1], settings.MIDDLEWARE)
        self.assertEqual(settings.SILENCED_SYSTEM_CHECKS, ["security.W003"])
        self.assertEqual([message.id for message in self.messages() if message.is_silenced()], ["security.W003"])
        self.run_deployment_check()

    def test_removing_csrf_still_fails_even_when_literal_path_warning_is_silenced(self):
        middleware = [path for path in settings.MIDDLEWARE if path not in CSRF_MIDDLEWARE]
        with override_settings(MIDDLEWARE=middleware):
            with self.assertRaisesMessage(SystemCheckError, "qc_tool.security.E001"):
                self.run_deployment_check()

    def test_custom_middleware_cannot_hide_an_insecure_csrf_cookie(self):
        with override_settings(CSRF_COOKIE_SECURE=False):
            with self.assertRaisesMessage(SystemCheckError, "qc_tool.security.E002"):
                self.run_deployment_check()

    def test_canonical_django_middleware_remains_supported_without_double_enforcement(self):
        middleware = [CSRF_MIDDLEWARE[0] if path == CSRF_MIDDLEWARE[1] else path for path in settings.MIDDLEWARE]
        with override_settings(MIDDLEWARE=middleware):
            self.run_deployment_check()
        with override_settings(MIDDLEWARE=[*settings.MIDDLEWARE, CSRF_MIDDLEWARE[0]]):
            with self.assertRaisesMessage(SystemCheckError, "qc_tool.security.E001"):
                self.run_deployment_check()

    def test_session_backed_csrf_keeps_the_secure_cookie_exception(self):
        with override_settings(CSRF_USE_SESSIONS=True, CSRF_COOKIE_SECURE=False):
            self.run_deployment_check()
