from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_request,
)
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission


def api_key_required(view_func=None, *, permission=None):
    """Authenticate an API request and expose its principal on the request."""

    required_permission = (
        AccountPermission(permission) if permission is not None else None
    )

    def decorator(decorated_view):
        @wraps(decorated_view)
        def wrapped(request, *args, **kwargs):
            user, message = authenticate_api_request(request)
            if user is None:
                response = JsonResponse(
                    {"status": "error", "message": message},
                    status=401,
                )
                response["WWW-Authenticate"] = 'ApiKey realm="QC Tool API"'
                return response

            access = access_for(user)
            if required_permission is not None and not access.allows(
                required_permission
            ):
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "account is not permitted to perform this action",
                    },
                    status=403,
                )

            request.api_user = user
            request.api_access = access
            return decorated_view(request, *args, **kwargs)

        # API-key clients do not authenticate with browser cookies.
        return csrf_exempt(wrapped)

    if view_func is None:
        return decorator
    return decorator(view_func)
