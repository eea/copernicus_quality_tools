"""Keep the standard sign-in flow available to maintenance operators."""

from importlib import import_module
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.maintenance import login_without_database_writes


class AccountLoginView(LoginView):
    def form_valid(self, form):
        if getattr(self.request, "maintenance_active", False):
            login_without_database_writes(self.request, form.get_user())
            return HttpResponseRedirect(self.get_success_url())
        if getattr(self.request, "_maintenance_cookie_session", False):
            # Switch only after CSRF and credentials were checked against the
            # former cookie session, including CSRF_USE_SESSIONS installations.
            self.request.session = import_module(settings.SESSION_ENGINE).SessionStore()
            self.request._maintenance_cookie_session = False
        return super().form_valid(form)


class AdminLoginView(AccountLoginView):
    """Keep Admin authentication destinations inside the Admin interface."""

    def get_redirect_url(self):
        redirect_url = super().get_redirect_url()
        if not redirect_url:
            return ""
        path = urlsplit(redirect_url).path
        decoded_path = unquote(path)
        if (
            not path.startswith(reverse("admin:index"))
            or "\\" in decoded_path
            or any(part in {".", ".."} for part in decoded_path.split("/"))
            or any(ord(character) < 32 or ord(character) == 127 for character in decoded_path)
        ):
            return ""
        return redirect_url
