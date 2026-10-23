"""Django-native account forms with identity and administrator safeguards."""

from django.contrib.auth.forms import AdminPasswordChangeForm, UserChangeForm
from django.core.exceptions import ValidationError

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.admin_users import validate_administrator_retention


class AdminUserChangeForm(UserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "username" in self.fields:
            self.fields["username"].disabled = True
            self.fields["username"].help_text = (
                "Usernames identify delivery storage and cannot be changed."
            )

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and not self.errors:
            groups = cleaned.get("groups")
            validate_administrator_retention(
                self.instance,
                is_active=cleaned.get("is_active", self.instance.is_active),
                is_superuser=cleaned.get("is_superuser", self.instance.is_superuser),
                has_admin_role=(any(group.name == Role.ADMIN.value for group in groups)
                                if groups is not None else None),
            )
        return cleaned


class AdminUserPasswordChangeForm(AdminPasswordChangeForm):
    def clean(self):
        cleaned = super().clean()
        if not self.errors and cleaned.get("set_usable_password") is False:
            try:
                validate_administrator_retention(self.user, has_usable_password=False)
            except ValidationError as exc:
                # Django's password template displays field errors only.
                self.add_error("usable_password", exc)
        return cleaned
