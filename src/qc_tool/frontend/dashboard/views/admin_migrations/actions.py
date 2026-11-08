"""Explicit HTTP confirmations; the database service owns every mutation."""

from django.contrib import messages
from django.http import HttpResponseRedirect

from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.upgrades import service
from qc_tool.frontend.accounts.authentication.maintenance import login_without_database_writes
from qc_tool.frontend.dashboard.forms.migrations import MigrationPreparationForm, activation_form

from .urls import migration_url


def _redirect(operation):
    return HttpResponseRedirect(migration_url(operation["id"]), status=303)


def _prepare(request, page):
    page.preparation_form = MigrationPreparationForm(request.POST)
    if page.preparation_form.is_valid():
        values = page.preparation_form.cleaned_data
        operation = service.start(str(values["backup_id"]), actor=request.user,
            review_hash=values["review_hash"], generation=values["generation"], revision=values["revision"])
        return _redirect(operation)
    page.status_code = 400
    # Rebuild read-only review without replacing the submitted confirmation.
    page.review = service.preview(request.POST.get("backup_id", ""), actor=request.user)


def _recover(request, page, action):
    operation = page.operation
    if action == "retry":
        if not operation.get("can_retry"):
            raise TransferError(operation.get("recovery_reason") or
                "This upgrade cannot be retried in its current state. Refresh its status and review the available recovery actions.")
    else:
        if not operation.get("can_abandon"):
            raise TransferError("This upgrade cannot be stopped in its current state. Refresh its status before choosing a recovery action.")
        if request.POST.get("confirmed_abandon") != "on":
            page.action_error = "Confirm that the failed copy and its recovery evidence will be retained."
            page.status_code = 400
            return
    service.recover(operation["id"], actor=request.user, action=action)
    if action == "abandon":
        messages.success(request, "The upgrade was stopped after verifying the retained source. The candidate, backup and journals are kept; maintenance remains on.")
    return _redirect(operation)


def _switch(request, page, action):
    operation = page.operation
    if operation.get("status") != "completed":
        raise TransferError("Complete and verify the upgraded copy before reviewing a database switch.")
    page.activation_review = service.activation_preview(operation["id"], actor=request.user)
    if action == "review_switch":
        return
    if not page.activation_review.get("can_apply"):
        raise TransferError("The upgraded copy is not ready to select. Review its verification and file availability first.")
    page.activation_form = activation_form(page.activation_review, data=request.POST)
    if not page.activation_form.is_valid():
        page.status_code = 400
        return
    if not getattr(request, "_maintenance_cookie_session", False):
        login_without_database_writes(request, request.user)
    service.activate(operation["id"], actor=request.user, **page.activation_form.cleaned_data)
    messages.success(request, "The upgraded database is selected. Maintenance remains on; the previous database and its files are retained.")
    return _redirect(operation)


def perform(request, page):
    """Dispatch only the supported administrator action vocabulary."""
    action = request.POST.get("action", "")
    if action == "review":
        page.review = service.preview(request.POST.get("backup_id", ""), actor=request.user)
    elif action == "start":
        return _prepare(request, page)
    elif action in {"retry", "abandon"} and page.operation:
        return _recover(request, page, action)
    elif action in {"review_switch", "activate"} and page.operation:
        return _switch(request, page, action)
    else:
        page.action_error, page.status_code = "Choose an available migration action.", 400
