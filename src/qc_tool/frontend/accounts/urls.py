from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.urls import path

from qc_tool.frontend.accounts.views.api_credentials import create_api_token
from qc_tool.frontend.accounts.views.api_credentials import delete_api_token
from qc_tool.frontend.accounts.views.passwords import change_password
from qc_tool.frontend.accounts.views.settings import account_settings


urlpatterns = [
    path("accounts/settings/", account_settings, name="account_settings"),
    path(
        "accounts/api-tokens/create/",
        create_api_token,
        name="api_token_create",
    ),
    path(
        "accounts/api-tokens/<int:token_id>/delete/",
        delete_api_token,
        name="api_token_delete",
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
