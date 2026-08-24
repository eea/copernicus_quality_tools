"""Authentication decorators for internal QC Tool worker callbacks."""

from functools import wraps

from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from django.views.decorators.csrf import csrf_exempt

from qc_tool.common import auth_worker
from qc_tool.worker_auth import MAX_WORKER_AUTHORIZATION_HEADER_LENGTH
from qc_tool.worker_auth import parse_worker_authorization
from qc_tool.worker_auth import WORKER_AUTHENTICATE_HEADER
from qc_tool.worker_auth import WORKER_AUTH_SCHEME


WORKER_AUTHORIZATION_HEADER = "Authorization"


def _disable_response_caching(response):
    """Keep worker credentials and claimed-job payloads out of caches."""

    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    patch_vary_headers(response, (WORKER_AUTHORIZATION_HEADER,))
    return response


def _get_worker_token(request):
    """Return a token from ``Authorization: WorkerToken <token>`` only."""

    if any(parameter.casefold() == "token" for parameter in request.GET):
        return None
    return parse_worker_authorization(
        request.headers.get(WORKER_AUTHORIZATION_HEADER)
    )


def _authentication_required_response():
    # Keep the worker protocol's status-only failure response. It is a machine
    # callback, so it does not need the browser/API JSON denial representation.
    response = HttpResponse(status=401)
    response["WWW-Authenticate"] = WORKER_AUTHENTICATE_HEADER
    return _disable_response_caching(response)


def worker_token_required(view_func):
    """Authenticate a worker request before invoking its route handler.

    Credentials are accepted only through the Authorization header. Query
    parameters are intentionally ignored because URLs are routinely retained
    in proxy, application, browser-history, and observability logs.

    Worker callbacks are exempt from browser CSRF tokens because they use a
    non-cookie machine credential. Authentication still happens before the
    endpoint can perform work.
    """

    @csrf_exempt
    @wraps(view_func)
    def protected_view(request, *args, **kwargs):
        token = _get_worker_token(request)
        if token is None or not auth_worker(token):
            return _authentication_required_response()
        response = view_func(request, *args, **kwargs)
        return _disable_response_caching(response)

    return protected_view
