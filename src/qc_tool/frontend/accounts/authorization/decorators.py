from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import resolve_url

from qc_tool.frontend.accounts.authorization.access import access_for_request
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.http import json_not_found_response
from qc_tool.frontend.accounts.http import prevent_private_response_caching


def account_permission_required(permission):
    """Require login and one explicit QC Tool application permission."""

    permission = AccountPermission(permission)

    def decorator(view_func):
        @wraps(view_func)
        def authorized(request, *args, **kwargs):
            if not access_for_request(request).allows(permission):
                raise PermissionDenied(
                    "Your account is not permitted to perform this action."
                )
            return view_func(request, *args, **kwargs)

        login_view = login_required(authorized)

        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            return prevent_private_response_caching(
                login_view(request, *args, **kwargs)
            )

        return wrapped

    return decorator


def session_login_url():
    """Resolve the configured browser login route."""

    return resolve_url(settings.LOGIN_URL)


def _json_permission_denied_response():
    return JsonResponse(
        {
            "status": "error",
            "code": "permission_denied",
            "message": "Your account is not permitted to perform this action.",
        },
        status=403,
    )


def account_json_permission_required(permission):
    """Authorize a session-backed data request without returning HTML."""

    permission = AccountPermission(permission)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            access = access_for_request(request)
            if not access.is_authenticated:
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

            if not access.allows(permission):
                return prevent_private_response_caching(
                    _json_permission_denied_response()
                )

            try:
                response = view_func(request, *args, **kwargs)
            except Http404:
                # Data endpoints keep their JSON contract while suppressing
                # model, identifier, and filesystem lookup details.
                response = json_not_found_response()
            except PermissionDenied:
                # Object-scope guards inside data views use the same JSON
                # response contract as the top-level capability check.
                response = _json_permission_denied_response()
            return prevent_private_response_caching(response)

        return wrapped

    return decorator
