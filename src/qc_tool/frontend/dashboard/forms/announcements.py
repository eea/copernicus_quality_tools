"""Validation for operator-managed dashboard announcements."""

from django import forms
from django.core.exceptions import ValidationError

from qc_tool.frontend.dashboard.services.configuration import (
    MAX_ANNOUNCEMENT_BYTES,
)


_MAX_ANNOUNCEMENT_KIB = MAX_ANNOUNCEMENT_BYTES // 1024


class AnnouncementForm(forms.Form):
    """Accept plain text that fits the announcement storage contract."""

    announcement_text = forms.CharField(
        label="Announcement message",
        required=False,
        strip=False,
        help_text=(
            "Use clear, concise text. HTML is displayed as plain text. "
            f"The message may use up to {_MAX_ANNOUNCEMENT_KIB} KiB when "
            "encoded as UTF-8."
        ),
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 7,
            }
        ),
    )

    def clean_announcement_text(self):
        """Enforce the byte limit used by the UTF-8 storage service."""

        message = self.cleaned_data["announcement_text"]
        try:
            payload = message.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValidationError(
                "Enter a message that can be encoded as UTF-8.",
                code="invalid_utf8",
            ) from exc

        if len(payload) > MAX_ANNOUNCEMENT_BYTES:
            raise ValidationError(
                "The announcement must be %(limit_kib)d KiB or smaller "
                "when encoded as UTF-8.",
                code="announcement_too_large",
                params={"limit_kib": _MAX_ANNOUNCEMENT_KIB},
            )
        return message
