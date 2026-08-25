from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from qc_tool.frontend.accounts.authorization import AccountPermission
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.authorization.decorators import (
    account_permission_required,
)
from qc_tool.frontend.accounts.forms import AccountPasswordChangeForm


@sensitive_post_parameters()
@account_permission_required(AccountPermission.CHANGE_PASSWORD)
@require_http_methods(("GET", "POST"))
def change_password(request):
    """Change a password when the central account policy permits it."""

    access = access_for_request(request)
    if access.can_manage_own_account:
        return_url = reverse("account_settings")
    elif access.can_view_deliveries:
        return_url = reverse("deliveries")
    else:
        return_url = "https://github.com/eea/copernicus_quality_tools/wiki"

    if request.method == "POST":
        form = AccountPasswordChangeForm(request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Password changed.")
            return redirect(return_url)
    else:
        form = AccountPasswordChangeForm(request.user)

    return render(
        request,
        "registration/change_password.html",
        {"form": form, "account_return_url": return_url},
    )
