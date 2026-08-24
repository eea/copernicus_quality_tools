from functools import wraps

from django.http import JsonResponse
from django.utils.cache import patch_vary_headers
from django.views.decorators.csrf import csrf_exempt

from qc_tool.frontend.accounts.authentication.api_keys import (
    ApiKeyAuthenticationError,
)
from qc_tool.frontend.accounts.authentication.api_keys import (
    authenticate_api_request,
)
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission


_BEARER_CHALLENGE = 'Bearer realm="QC Tool API"'


def _secure_api_response(response):
    """Prevent credential-scoped API responses from being cached or shared."""

    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    patch_vary_headers(response, ("Authorization",))
    return response


def _authentication_failure(error):
    if error is ApiKeyAuthenticationError.MISSING:
        code = "authentication_required"
        message = "A Bearer API credential is required."
        challenge = _BEARER_CHALLENGE
    elif error is ApiKeyAuthenticationError.QUERY_PARAMETER:
        code = error.value
        message = "API credentials must be sent in the Authorization header."
        challenge = f'{_BEARER_CHALLENGE}, error="invalid_token"'
    else:
        code = "invalid_token"
        message = "The Bearer API credential is invalid."
        challenge = f'{_BEARER_CHALLENGE}, error="invalid_token"'

    response = JsonResponse(
        {"status": "error", "code": code, "message": message},
        status=401,
    )
    response["WWW-Authenticate"] = challenge
    return _secure_api_response(response)


def api_key_required(view_func=None, *, permission=None):
    """Authenticate a Bearer API credential before authorizing the request."""

    required_permission = (
        AccountPermission(permission) if permission is not None else None
    )

    def decorator(decorated_view):
        @wraps(decorated_view)
        def wrapped(request, *args, **kwargs):
            authentication = authenticate_api_request(request)
            if not authentication.is_authenticated:
                return _authentication_failure(authentication.error)

            access = access_for(authentication.user)
            if required_permission is not None and not access.allows(
                required_permission
            ):
                return _secure_api_response(
                    JsonResponse(
                        {
                            "status": "error",
                            "code": "permission_denied",
                            "message": (
                                "The account is not permitted to perform "
                                "this action."
                            ),
                        },
                        status=403,
                    )
                )

            request.api_user = authentication.user
            request.api_access = access
            return _secure_api_response(decorated_view(request, *args, **kwargs))

        # This endpoint authenticates exclusively with a non-cookie Bearer
        # credential, so browser CSRF tokens are neither needed nor useful.
        return csrf_exempt(wrapped)

    if view_func is None:
        return decorator
    return decorator(view_func)
