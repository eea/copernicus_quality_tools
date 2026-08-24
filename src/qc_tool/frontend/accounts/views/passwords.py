from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect
from django.shortcuts import render

from qc_tool.frontend.accounts.authorization import AccountPermission
from qc_tool.frontend.accounts.authorization.decorators import (
    account_permission_required,
)


@account_permission_required(AccountPermission.CHANGE_PASSWORD)
def change_password(request):
    """Change a password when the central account policy permits it."""

    if request.method == "POST":
        form = PasswordChangeForm(request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)
            messages.success(request, "Password changed.")
            return redirect("/")
    else:
        form = PasswordChangeForm(request.user)

    return render(
        request,
        "registration/change_password.html",
        {"form": form},
    )
