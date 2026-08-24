"""Authentication decorators for internal QC Tool worker callbacks."""

from functools import wraps

from django.http import HttpResponse

from qc_tool.common import auth_worker


WORKER_AUTHENTICATE_HEADER = 'WorkerToken realm="QC Tool Worker"'


def _authentication_required_response():
    # Keep the worker protocol's status-only failure response. It is a machine
    # callback, so it does not need the browser/API JSON denial representation.
    response = HttpResponse(status=401)
    response["WWW-Authenticate"] = WORKER_AUTHENTICATE_HEADER
    return response


def worker_token_required(view_func):
    """Authenticate a worker request before invoking its route handler.

    The query-string token transport is retained for compatibility with the
    existing worker client. Keeping extraction and verification here prevents
    an endpoint from doing any work before its machine credential is checked.
    """

    @wraps(view_func)
    def protected_view(request, *args, **kwargs):
        token = request.GET.get("token")
        if token is None or not auth_worker(token):
            return _authentication_required_response()
        return view_func(request, *args, **kwargs)

    return protected_view
