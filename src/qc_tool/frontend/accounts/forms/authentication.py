"""Presentation defaults for Django's standard sign-in form."""

from django.contrib.auth.forms import AuthenticationForm
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError

from qc_tool.frontend.accounts.authorization.access import AccountAccess


class AccountAuthenticationForm(AuthenticationForm):
    """Render styled, labelled controls without a JavaScript dependency."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()
        self.fields["username"].widget.attrs["autocomplete"] = "username"

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if (getattr(self.request, "maintenance_active", False)
                and not AccountAccess.from_user(user).can_access_django_admin):
            raise ValidationError(
                "Only administrators and product managers can sign in during maintenance.",
                code="maintenance",
            )


class AccountAdminAuthenticationForm(AccountAuthenticationForm, AdminAuthenticationForm):
    """Retain Django Admin's staff check as well as maintenance role policy."""
