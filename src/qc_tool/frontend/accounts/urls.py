from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.urls import path

from qc_tool.frontend.accounts.views.api_credentials import (
    revoke_api_credential,
)
from qc_tool.frontend.accounts.views.api_credentials import (
    rotate_api_credential,
)
from qc_tool.frontend.accounts.views.passwords import change_password
from qc_tool.frontend.accounts.views.settings import account_settings


urlpatterns = [
    path("accounts/settings/", account_settings, name="account_settings"),
    path(
        "accounts/api-credentials/rotate/",
        rotate_api_credential,
        name="api_credential_rotate",
    ),
    path(
        "accounts/api-credentials/revoke/",
        revoke_api_credential,
        name="api_credential_revoke",
    ),
    path("change_password/", change_password, name="change_password"),
    path("accounts/password_change/", change_password, name="password_change"),
    path(
        "accounts/login/",
        LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
]
