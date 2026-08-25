"""Forms for self-service account management."""

from qc_tool.frontend.accounts.forms.profile import AccountProfileForm
from qc_tool.frontend.accounts.forms.passwords import AccountPasswordChangeForm

__all__ = ["AccountPasswordChangeForm", "AccountProfileForm"]
