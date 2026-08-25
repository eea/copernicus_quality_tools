"""Forms for changing the current account's authentication secret."""

from django.contrib.auth.forms import PasswordChangeForm


class AccountPasswordChangeForm(PasswordChangeForm):
    """Apply the shared form-control contract to Django's secure form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = "{} form-control".format(
                existing_class
            ).strip()
