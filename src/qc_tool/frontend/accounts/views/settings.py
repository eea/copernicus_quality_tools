"""Session-authenticated self-service account settings."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from qc_tool.frontend.accounts.authentication.api_keys import has_api_key
from qc_tool.frontend.accounts.authorization import AccountPermission
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.authorization.decorators import (
    account_any_permission_required,
)
from qc_tool.frontend.accounts.forms import AccountProfileForm


@sensitive_post_parameters("first_name", "last_name", "email")
@account_any_permission_required(
    AccountPermission.MANAGE_OWN_ACCOUNT,
    AccountPermission.MANAGE_API_CREDENTIAL,
)
@require_http_methods(("GET", "POST"))
def account_settings(request):
    """Display only the self-service sections allowed for this account."""

    access = access_for_request(request)

    if request.method == "POST":
        if not access.can_manage_own_account:
            raise PermissionDenied(
                "Your account is not permitted to update profile details."
            )
        profile_form = AccountProfileForm(request.POST, instance=request.user)
        if profile_form.is_valid():
            profile = profile_form.save(commit=False)
            profile.save(update_fields=("first_name", "last_name", "email"))
            messages.success(request, "Your profile details were updated.")
            return redirect("account_settings")
    elif access.can_manage_own_account:
        profile_form = AccountProfileForm(instance=request.user)
    else:
        profile_form = None

    api_key_configured = bool(
        access.can_manage_api_credential and has_api_key(request.user)
    )
    return render(
        request,
        "accounts/settings/index.html",
        {
            "profile_form": profile_form,
            "api_key_configured": api_key_configured,
        },
    )
