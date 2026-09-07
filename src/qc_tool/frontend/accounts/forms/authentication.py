"""Presentation defaults for Django's standard sign-in form."""

from django.contrib.auth.forms import AuthenticationForm


class AccountAuthenticationForm(AuthenticationForm):
    """Render styled, labelled controls without a JavaScript dependency."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()
        self.fields["username"].widget.attrs["autocomplete"] = "username"
