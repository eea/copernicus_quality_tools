"""Database-free browser sessions for maintenance operators.

Use Django's signed-cookie backend and authentication session keys, without
emitting login signals that update SQL. Normal sign-in keeps Django's configured
session backend and login behavior.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.exceptions import PermissionDenied
from django.middleware.csrf import rotate_token

from qc_tool.frontend.accounts.authorization.access import AccountAccess
from qc_tool.database import selection
from django.db import connections


MARKER = "_qc_maintenance_login"
GENERATION = "_qc_maintenance_generation"
ORIGIN_DATABASE = "_qc_maintenance_origin_database"
BACKEND = "qc_tool.frontend.accounts.authentication.backends.MaintenanceBackend"
_authentication_origin = ContextVar("qc_maintenance_authentication_origin", default=None)


def authentication_origin():
    return _authentication_origin.get()


@contextmanager
def authentication_scope(origin):
    token = _authentication_origin.set(origin)
    try:
        yield
    finally:
        _authentication_origin.reset(token)


class MaintenanceSessionStore(SessionStore):
    def get_session_cookie_age(self):
        return min(super().get_session_cookie_age(), 30 * 60)


def cookie_session(value):
    """Recognize only a signed maintenance session, never a client role flag."""
    if value:
        session = MaintenanceSessionStore(value)
        if session.get(MARKER) is True:
            return session
    return None


def login_without_database_writes(request, user):
    if not AccountAccess.from_user(user).can_access_django_admin:
        raise PermissionDenied
    # Replace the browser's former session without deleting a database row.
    # A new signed payload prevents reusing another identity's session data.
    request.session = MaintenanceSessionStore()
    request.session.update({
        MARKER: True,
        GENERATION: request.maintenance_status["generation"],
        SESSION_KEY: user._meta.pk.value_to_string(user),
        BACKEND_SESSION_KEY: BACKEND,
        HASH_SESSION_KEY: user.get_session_auth_hash(),
        ORIGIN_DATABASE: (
            selection.current_database() if user._state.db in {None, "default"}
            else connections[user._state.db].settings_dict["NAME"]
        ),
    })
    request._maintenance_cookie_session = True
    request._maintenance_readonly_session = False
    request.user = user
    request._cached_user = user
    request.__dict__.pop("_qc_tool_account_access", None)
    rotate_token(request)
