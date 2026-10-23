"""Fence application requests before sessions, authentication and uploads."""

from django.http import JsonResponse
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.contrib.sessions.middleware import SessionMiddleware
from django.conf import settings
from django.db import DatabaseError
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CSRF_SESSION_KEY
from django.urls import reverse

from qc_tool.frontend.admin_site import is_admin_request

from qc_tool.frontend.accounts.authentication.maintenance import (
    GENERATION, MARKER, ORIGIN_DATABASE, MaintenanceSessionStore, cookie_session,
    authentication_scope,
)
from qc_tool.frontend.accounts.authorization.access import AccountAccess

from qc_tool.frontend.dashboard.access.maintenance import (
    is_maintenance_control_request, is_maintenance_read_request,
    is_maintenance_login_request,
)
from qc_tool.frontend.dashboard.services.maintenance import (
    MaintenanceError, application_activity, read_status,
)
from qc_tool.frontend.dashboard.services.maintenance.reads import (
    MaintenanceWriteBlocked, ReadOnlyStream, read_only_database_access,
)


class _ActivityStream:
    """Release admission through the public WSGI iterator/close protocol."""

    def __init__(self, content, release):
        self._content = iter(content)
        self._release = release
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        # Exhaustion does not close a response's registered resources. A
        # source can still persist state in close(), even after its iterator
        # finishes or raises. WSGI closes the response on both paths; retain
        # admission until its original closers have run before this closer.
        return next(self._content)

    def close(self):
        if not self._closed:
            self._closed = True
            self._release()


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # A liveness probe must not touch sessions or the application DB.
        if request.path_info == "/health" and request.method in {"GET", "HEAD"}:
            return JsonResponse({"status": "ok"})
        # Controls authenticate independently and may reconcile job state.
        if is_maintenance_control_request(request):
            try:
                self._set_state(request, read_status())
            except MaintenanceError:
                self._set_state(request, {"enabled": True, "phase": "unavailable"})
            if request.maintenance_active and request.method in {"GET", "HEAD"}:
                return self._browse(request)
            return self.get_response(request)
        try:
            self._set_state(request, read_status())
        except MaintenanceError:
            self._set_state(request, {"enabled": True, "phase": "unavailable"})
            return self._unavailable(request)
        if request.maintenance_active:
            return self._during_maintenance(request)
        activity = application_activity()
        try:
            admitted = activity.__enter__()
        except MaintenanceError:
            admitted = False
            activity = None
        if admitted:
            released = False

            def release():
                nonlocal released
                if not released:
                    released = True
                    activity.__exit__(None, None, None)

            try:
                response = self.get_response(request)
                if response.streaming:
                    # The public setter registers the supplied iterator's
                    # close method, including when it is never consumed.
                    # Django retains the original stream/FileResponse closers.
                    response.streaming_content = _ActivityStream(
                        response.streaming_content, release,
                    )
                else:
                    release()
                response["X-QC-Maintenance"] = "off"
                return response
            except BaseException:
                release()
                raise
        if activity is not None:
            activity.__exit__(None, None, None)
        # Enabling may race the first state read. Reclassify under the new
        # state so a reader never falls back to the former blanket 503 page.
        try:
            self._set_state(request, read_status())
        except MaintenanceError:
            self._set_state(request, {"enabled": True, "phase": "unavailable"})
            return self._unavailable(request)
        return self._during_maintenance(request)

    @staticmethod
    def _set_state(request, state):
        request.maintenance_status = state
        request.maintenance_active = state["enabled"]

    def _during_maintenance(self, request):
        if is_maintenance_read_request(request) or is_maintenance_login_request(request):
            return self._browse(request)
        return self._unavailable(request)

    def _browse(self, request):
        # Reads started after the fence do not hold the writer-drain lock.
        # Keep the query guard scoped to execution rather than an unconsumed
        # response's lifetime: WSGI may reuse a thread for a later request.
        with read_only_database_access():
            response = self.get_response(request)
        if response.streaming:
            response.streaming_content = ReadOnlyStream(response.streaming_content)
            original_close = response.close

            def close():
                with read_only_database_access():
                    original_close()

            response.close = close
        response["X-QC-Maintenance"] = "on"
        response["Cache-Control"] = "no-store, private"
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, MaintenanceWriteBlocked):
            return self._unavailable(request)

    @staticmethod
    def _unavailable(request):
        if request.path_info.startswith("/api") or request.headers.get("Accept") == "application/json":
            response = JsonResponse({"error": "maintenance", "code": "maintenance", "message": "Maintenance is in progress. You can browse existing data, but changes are temporarily unavailable."}, status=503)
        else:
            # This path also handles an ORM write rejected inside an atomic
            # block. Keep the error page independent of DB context processors
            # until the read scope rolls its savepoint back.
            admin_request = is_admin_request(request)
            response = HttpResponse(render_to_string("dashboard/system/maintenance.html", {
                "return_url": reverse("admin:index" if admin_request else "dashboard_home"),
                "return_label": "Return to administration" if admin_request else "Return to QC Tool",
                "maintenance_url": reverse("admin_maintenance"),
            }), status=503)
        response["Retry-After"] = "60"
        response["Cache-Control"] = "no-store, private"
        response["X-QC-Maintenance"] = "on"
        return response


class MaintenanceSessionMiddleware(SessionMiddleware):
    """The control channel can read authentication without writing sessions.

    Django may delete invalid sessions during authentication or save them on
    response. Neither is permitted after the application declares readiness.
    Operator sign-in uses a signed browser cookie, so it can remain available
    without writing database sessions or authentication timestamps.
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        session_key_salt = self.SessionStore().key_salt

        class ReadOnlySessionStore(self.SessionStore):
            # SessionBase normally derives this from the subclass name.
            # Preserve signatures issued by the configured session backend.
            key_salt = session_key_salt

            def load(self):
                try:
                    return super().load()
                except DatabaseError:
                    return {}

            async def aload(self):
                try:
                    return await super().aload()
                except DatabaseError:
                    return {}

            def save(self, must_create=False):
                pass

            def create(self):
                pass

            def delete(self, session_key=None):
                pass

            async def asave(self, must_create=False):
                pass

            async def acreate(self):
                pass

            async def adelete(self, session_key=None):
                pass

        self.ReadOnlySessionStore = ReadOnlySessionStore

    def __call__(self, request):
        from qc_tool.database.middleware import scope_response

        signed = cookie_session(request.COOKIES.get(settings.SESSION_COOKIE_NAME))
        origin = signed.get(ORIGIN_DATABASE) if signed is not None else None
        scope = lambda: authentication_scope(origin)
        with scope():
            response = super().__call__(request)
        return scope_response(response, scope)

    def process_request(self, request):
        super().process_request(request)
        signed = cookie_session(request.COOKIES.get(settings.SESSION_COOKIE_NAME))
        if signed is not None:
            request.session = signed
            request._maintenance_cookie_session = True
            valid_window = (
                getattr(request, "maintenance_active", False)
                and signed.get(GENERATION) == request.maintenance_status.get("generation")
            )
            if signed.get(SESSION_KEY) and (not signed.get(ORIGIN_DATABASE) or not valid_window):
                # A pre-switch cookie without a bound database must never
                # reinterpret the same account primary key in another copy.
                for key in (SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY):
                    request.session.pop(key, None)
            return
        if getattr(request, "maintenance_active", False) or is_maintenance_control_request(request):
            request.session = self.ReadOnlySessionStore(request.session.session_key)
            request._maintenance_readonly_session = True
            if (getattr(request, "maintenance_active", False)
                    and is_maintenance_login_request(request)
                    and (not request.session.get(SESSION_KEY)
                         or (settings.CSRF_USE_SESSIONS and not request.session.get(CSRF_SESSION_KEY)))):
                # Preserve existing authenticated browser sessions. A visitor
                # without a usable session can hold CSRF state in a cookie.
                request.session = MaintenanceSessionStore()
                request.session[MARKER] = True
                request._maintenance_cookie_session = True
                request._maintenance_readonly_session = False

    def process_view(self, request, view_func, view_args, view_kwargs):
        if (getattr(request, "_maintenance_cookie_session", False)
                and request.user.is_authenticated):
            same_window = (
                getattr(request, "maintenance_active", False)
                and request.session.get(GENERATION) == request.maintenance_status.get("generation")
            )
            if not same_window or not AccountAccess.from_user(request.user).can_access_django_admin:
                # Recheck current roles and bind this credential to one pause.
                # Preserve CSRF state so normal sign-in works after reopening.
                for key in (SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY):
                    request.session.pop(key, None)
                request.user = request._cached_user = AnonymousUser()
                request.__dict__.pop("_qc_tool_account_access", None)

    def process_response(self, request, response):
        if getattr(request, "_maintenance_readonly_session", False):
            # Also bypass SESSION_SAVE_EVERY_REQUEST if an installation sets it.
            response.headers.setdefault("Cache-Control", "no-store, private")
            return response
        return super().process_response(request, response)
