"""Route-aware formatting for Django's CSRF rejection responses."""

import errno
import logging

from django.contrib.auth import get_user
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.views.csrf import csrf_failure as django_csrf_failure

from qc_tool.frontend.accounts.authorization.decorators import session_login_url
from qc_tool.frontend.accounts.http import prevent_private_response_caching
from qc_tool.frontend.dashboard.access.routes.policies import AuthenticationMode
from qc_tool.frontend.dashboard.access.routes.policies import DenialResponse
from qc_tool.frontend.dashboard.access.routes.policies import RouteVisibility
from qc_tool.frontend.dashboard.access.routes.request_policy import (
    policy_for_request,
)


logger = logging.getLogger(__name__)


def boundary_upload_receive_failure(error):
    """Use one safe response before or inside the boundary upload view."""
    if error.errno in {errno.ENOSPC, errno.EDQUOT}:
        logger.warning("Boundary upload could not be received: temporary storage is full")
        response = JsonResponse({
            "is_valid": False, "code": "boundary_upload_insufficient_space",
            "message": "The server ran out of temporary upload space. Free server storage, reload this page and try again. No boundary package was activated.",
        }, status=507)
    else:
        logger.error("Boundary upload could not be received", exc_info=(type(error), error, error.__traceback__))
        response = JsonResponse({
            "is_valid": False, "code": "boundary_upload_unavailable",
            "message": "The server could not receive the ZIP. Check upload storage before retrying. No boundary package was activated.",
        }, status=503)
    return prevent_private_response_caching(response)


class UploadAwareCsrfViewMiddleware(CsrfViewMiddleware):
    """Keep Django CSRF enforcement, including multipart storage failures.

    Django reads POST data before checking the token even when the browser sent
    X-CSRFToken. Spooling can therefore fail before the protected view runs.
    Translate only that upload route's I/O failure; normal CSRF checks and all
    other routes delegate unchanged to Django.
    """

    def process_view(self, request, callback, callback_args, callback_kwargs):
        try:
            return super().process_view(request, callback, callback_args, callback_kwargs)
        except OSError as error:
            route = getattr(getattr(request, "resolver_match", None), "url_name", None)
            if (route == "boundaries_upload_data" and request.method == "POST"
                    and request.content_type == "multipart/form-data"):
                return boundary_upload_receive_failure(error)
            raise


def _uses_session_data_policy(request):
    """Return whether CSRF rejected a private, session-backed data route."""

    policy = policy_for_request(request)
    return (
        policy is not None
        and policy.visibility is RouteVisibility.PRIVATE
        and policy.authentication is AuthenticationMode.SESSION
        and policy.denial_response is DenialResponse.JSON
    )


def csrf_failure(request, reason=""):
    """Format a CSRF rejection according to the resolved route policy.

    CSRF validation still happens before the protected callback runs. Only
    private session data routes use JSON; forms and pages retain Django's HTML
    failure response, and API-key routes remain independently CSRF-exempt.
    """

    if not _uses_session_data_policy(request):
        return django_csrf_failure(request, reason=reason)

    user = getattr(request, "user", None)
    if user is None:
        user = get_user(request)

    if not user.is_authenticated:
        login_url = session_login_url()
        response = JsonResponse(
            {
                "status": "error",
                "code": "authentication_required",
                "message": "Your session has expired. Please sign in again.",
                "login_url": login_url,
            },
            status=401,
        )
        response["X-Login-URL"] = login_url
        return prevent_private_response_caching(response)

    return prevent_private_response_caching(
        JsonResponse(
            {
                "status": "error",
                "code": "csrf_failed",
                "message": (
                    "Security verification failed. Refresh the page and try again."
                ),
            },
            status=403,
        )
    )
