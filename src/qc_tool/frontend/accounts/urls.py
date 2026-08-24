from django.contrib.auth.views import LoginView
from django.contrib.auth.views import LogoutView
from django.urls import path

from qc_tool.frontend.accounts.views.passwords import change_password


urlpatterns = [
    path("change_password/", change_password, name="change_password"),
    path("accounts/password_change/", change_password, name="password_change"),
    path(
        "accounts/login/",
        LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
]
