"""Session-authenticated, self-service API credential lifecycle views."""

from django.contrib import messages
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from qc_tool.frontend.accounts.authentication.api_keys import (
    issue_or_rotate_api_key,
)
from qc_tool.frontend.accounts.authentication.api_keys import revoke_api_key
from qc_tool.frontend.accounts.authorization import AccountPermission
from qc_tool.frontend.accounts.authorization.decorators import (
    account_permission_required,
)


def _secure_credential_response(response):
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@account_permission_required(AccountPermission.MANAGE_API_CREDENTIAL)
@require_POST
@sensitive_variables()
def rotate_api_credential(request):
    """Issue or rotate the current user's API key and display it once."""

    raw_key = issue_or_rotate_api_key(request.user)
    response = render(
        request,
        "accounts/api_credentials/issued.html",
        {"api_key": raw_key},
    )
    return _secure_credential_response(response)


@account_permission_required(AccountPermission.MANAGE_API_CREDENTIAL)
@require_POST
def revoke_api_credential(request):
    """Revoke the current user's API key and return to account settings."""

    revoked = revoke_api_key(request.user)
    if revoked:
        messages.success(request, "Your API token was revoked.")
    else:
        messages.info(request, "No API token was configured.")
    return _secure_credential_response(redirect("account_settings"))
