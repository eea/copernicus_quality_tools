from django.urls import include
from django.urls import path

from qc_tool.frontend.accounts.views.passwords import change_password


urlpatterns = [
    path("change_password/", change_password, name="change_password"),
    # Override Django's built-in password-change URL with the same policy.
    path("accounts/password_change/", change_password, name="password_change"),
    # Keep browser authentication routes owned by the accounts app while
    # delegating session handling to Django's maintained auth views.
    path("accounts/", include("django.contrib.auth.urls")),
]
