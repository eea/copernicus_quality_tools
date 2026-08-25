"""Session-authenticated self-service account settings."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from qc_tool.frontend.accounts.authorization import AccountPermission
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.authorization.decorators import (
    account_any_permission_required,
)
from qc_tool.frontend.accounts.forms import AccountProfileForm
from qc_tool.frontend.accounts.forms import PersonalApiTokenCreateForm
from qc_tool.frontend.accounts.services.api_tokens import api_token_presentations


def render_account_settings(
    request,
    *,
    profile_form=None,
    api_token_form=None,
    status=200,
):
    """Render the permission-aware settings page from one reusable context."""

    access = access_for_request(request)
    if profile_form is None and access.can_manage_own_account:
        profile_form = AccountProfileForm(instance=request.user)
    if api_token_form is None and access.can_manage_api_credential:
        api_token_form = PersonalApiTokenCreateForm(user=request.user)

    api_tokens = (
        api_token_presentations(request.user)
        if access.can_manage_api_credential
        else ()
    )
    return render(
        request,
        "accounts/settings/index.html",
        {
            "profile_form": profile_form,
            "api_token_form": api_token_form,
            "api_tokens": api_tokens,
        },
        status=status,
    )


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
    else:
        profile_form = None

    return render_account_settings(request, profile_form=profile_form)
