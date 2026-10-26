"""Deployment checks for the reviewed, upload-aware Django CSRF replacement."""

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.module_loading import import_string


CSRF_MIDDLEWARE = (
    "django.middleware.csrf.CsrfViewMiddleware",
    "qc_tool.frontend.dashboard.access.routes.csrf.UploadAwareCsrfViewMiddleware",
)


@register(Tags.security, deploy=True)
def check_csrf_protection(app_configs, **kwargs):
    """Replace Django's literal-path checks without weakening their guarantees.

    Django 5.2's security.W003 does not recognize subclasses; security.W016
    also skips secure-cookie validation when its canonical path is absent.
    Accept only the two explicitly reviewed implementations, exactly once.
    """
    configured = [path for path in settings.MIDDLEWARE if path in CSRF_MIDDLEWARE]
    errors = []
    try:
        protected = len(configured) == 1 and issubclass(import_string(configured[0]), CsrfViewMiddleware)
    except (ImportError, AttributeError, TypeError):
        protected = False
    if not protected:
        errors.append(Error(
            "Configure exactly one reviewed Django CSRF middleware.",
            hint="Use UploadAwareCsrfViewMiddleware or Django's CsrfViewMiddleware in MIDDLEWARE.",
            id="qc_tool.security.E001",
        ))
    if not settings.CSRF_USE_SESSIONS and settings.CSRF_COOKIE_SECURE is not True:
        errors.append(Error(
            "The CSRF cookie must be secure in a deployed application.",
            hint="Set CSRF_COOKIE_SECURE=True or use CSRF_USE_SESSIONS=True with secure sessions.",
            id="qc_tool.security.E002",
        ))
    return errors
