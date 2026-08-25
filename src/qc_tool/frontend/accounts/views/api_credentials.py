"""Session-authenticated, self-service API credential lifecycle views."""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from qc_tool.frontend.accounts.authorization import AccountPermission
from qc_tool.frontend.accounts.authorization.decorators import (
    account_permission_required,
)
from qc_tool.frontend.accounts.forms import PersonalApiTokenCreateForm
from qc_tool.frontend.accounts.services.api_tokens import ApiTokenIssuanceError
from qc_tool.frontend.accounts.services.api_tokens import (
    delete_personal_access_token,
)
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.accounts.views.settings import render_account_settings


def _secure_credential_response(response):
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@sensitive_post_parameters("current_password")
@account_permission_required(AccountPermission.MANAGE_API_CREDENTIAL)
@require_POST
@sensitive_variables("issued")
def create_api_token(request):
    """Create one named token after verifying the current password."""

    form = PersonalApiTokenCreateForm(request.POST, user=request.user)
    if not form.is_valid():
        return render_account_settings(
            request,
            api_token_form=form,
            status=400,
        )

    try:
        issued = issue_personal_access_token(
            request.user,
            form.cleaned_data["name"],
        )
    except ApiTokenIssuanceError as exc:
        field = "name" if exc.code in {
            "duplicate_name",
            "invalid_name",
            "token_conflict",
        } else None
        form.add_error(field, exc.message)
        return render_account_settings(
            request,
            api_token_form=form,
            status=400,
        )

    response = render(
        request,
        "accounts/api_credentials/issued.html",
        {"raw_token": issued.raw_token, "token": issued.token},
    )
    return _secure_credential_response(response)


@account_permission_required(AccountPermission.MANAGE_API_CREDENTIAL)
@require_POST
def delete_api_token(request, token_id):
    """Delete exactly one token owned by the authenticated account."""

    token_name = delete_personal_access_token(request.user, token_id)
    if token_name is None:
        raise Http404
    messages.success(request, 'The API token "{}" was deleted.'.format(token_name))
    destination = "{}#api-tokens".format(reverse("account_settings"))
    return _secure_credential_response(redirect(destination))
