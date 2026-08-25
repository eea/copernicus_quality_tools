"""Forms for creating personal API tokens securely."""

from django import forms

from qc_tool.frontend.accounts.services.api_tokens import normalize_token_name


class PersonalApiTokenCreateForm(forms.Form):
    """Validate a token label and recent proof of the user's password."""

    name = forms.CharField(
        label="Token name",
        max_length=80,
        help_text="Use a name that identifies the application or device.",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "class": "form-control",
                "placeholder": "For example: Data import script",
            }
        ),
    )
    current_password = forms.CharField(
        label="Current password",
        help_text="Confirm your password before creating a long-lived token.",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "class": "form-control",
            }
        ),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_name(self):
        return normalize_token_name(self.cleaned_data["name"])

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user.has_usable_password():
            raise forms.ValidationError(
                "This account cannot verify a local password. Contact an "
                "administrator before creating an API token.",
                code="unusable_password",
            )
        if not self.user.check_password(password):
            raise forms.ValidationError(
                "Enter your current password.",
                code="invalid_password",
            )
        return password
