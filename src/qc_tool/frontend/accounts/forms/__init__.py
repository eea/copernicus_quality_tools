"""Forms for self-service account management."""

from qc_tool.frontend.accounts.forms.api_tokens import PersonalApiTokenCreateForm
from qc_tool.frontend.accounts.forms.authentication import AccountAuthenticationForm
from qc_tool.frontend.accounts.forms.profile import AccountProfileForm
from qc_tool.frontend.accounts.forms.passwords import AccountPasswordChangeForm

__all__ = [
    "AccountAuthenticationForm",
    "AccountPasswordChangeForm",
    "AccountProfileForm",
    "PersonalApiTokenCreateForm",
]
