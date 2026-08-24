"""Route-aware formatting for Django's CSRF rejection responses."""

from django.contrib.auth import get_user
from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure

from qc_tool.frontend.accounts.authorization.decorators import session_login_url
from qc_tool.frontend.accounts.http import prevent_private_response_caching
from qc_tool.frontend.dashboard.access.routes.policies import AuthenticationMode
from qc_tool.frontend.dashboard.access.routes.policies import DenialResponse
from qc_tool.frontend.dashboard.access.routes.policies import RouteVisibility
from qc_tool.frontend.dashboard.access.routes.request_policy import (
    policy_for_request,
)


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
