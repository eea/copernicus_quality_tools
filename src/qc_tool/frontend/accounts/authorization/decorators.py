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


def account_permission_required(permission, *, login_url=None):
    """Require login and one explicit QC Tool application permission."""

    return _account_access_required(
        (permission,), require_all=True, login_url=login_url,
    )


def _account_access_required(permissions, *, require_all, login_url=None):
    """Build a cached browser authorization decorator for a permission set."""

    required_permissions = tuple(
        AccountPermission(permission) for permission in permissions
    )
    if not required_permissions:
        raise ValueError("At least one account permission is required.")

    def decorator(view_func):
        @wraps(view_func)
        def authorized(request, *args, **kwargs):
            access = access_for_request(request)
            decisions = (
                access.allows(permission) for permission in required_permissions
            )
            is_allowed = all(decisions) if require_all else any(decisions)
            if not is_allowed:
                raise PermissionDenied(
                    "Your account is not permitted to perform this action."
                )
            return view_func(request, *args, **kwargs)

        login_view = login_required(authorized, login_url=login_url)

        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            return prevent_private_response_caching(
                login_view(request, *args, **kwargs)
            )

        return wrapped

    return decorator


def account_permissions_required(*permissions):
    """Require login and every declared QC Tool application permission."""

    return _account_access_required(permissions, require_all=True)


def account_any_permission_required(*permissions):
    """Require login and at least one declared application permission."""

    return _account_access_required(permissions, require_all=False)


def session_login_url(*, admin=False):
    """Keep session recovery inside the owning workspace."""

    return resolve_url("admin_login" if admin else settings.LOGIN_URL)


def _json_permission_denied_response():
    return JsonResponse(
        {
            "status": "error",
            "code": "permission_denied",
            "message": "Your account is not permitted to perform this action.",
        },
        status=403,
    )


def account_json_permission_required(permission, *, login_url=None):
    """Authorize a session-backed data request without returning HTML."""

    permission = AccountPermission(permission)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            access = access_for_request(request)
            if not access.is_authenticated:
                resolved_login_url = (
                    resolve_url(login_url) if login_url else session_login_url()
                )
                response = JsonResponse(
                    {
                        "status": "error",
                        "code": "authentication_required",
                        "message": "Your session has expired. Please sign in again.",
                        "login_url": resolved_login_url,
                    },
                    status=401,
                )
                response["X-Login-URL"] = resolved_login_url
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


def administrator_permission_required(permission, *, json_response=False):
    """Require Admin membership while keeping page/data recovery in Admin.

    Account permissions still govern the operation. Staff status alone or a
    directly granted configuration permission cannot grant QC administration.
    Authenticated denials use 403 rather than restarting the sign-in flow.
    """

    def decorator(view_func):
        @wraps(view_func)
        def authorized(request, *args, **kwargs):
            if not (
                getattr(request.user, "is_staff", False)
                and access_for_request(request).is_administrator
            ):
                raise PermissionDenied(
                    "Your account is not permitted to perform this action."
                )
            return view_func(request, *args, **kwargs)

        permission_decorator = (
            account_json_permission_required if json_response
            else account_permission_required
        )
        return permission_decorator(permission, login_url="admin_login")(authorized)

    return decorator
