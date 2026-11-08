"""Administrator-only HTML and polling endpoints for installed migration plans."""

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters

from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.upgrades import service
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.http.cache import prevent_private_response_caching
from qc_tool.frontend.dashboard.services.admin_feedback import busy_context

from .actions import perform
from .context import page_context
from .state import MigrationPage


def _authorize(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied


def _error_status(error):
    value = getattr(error, "status_code", 409)
    return value if value in {400, 404, 409, 422, 503} else 409


@sensitive_post_parameters("activation-password")
def migrations(request):
    _authorize(request)
    if request.method not in {"GET", "POST"}:
        return prevent_private_response_caching(HttpResponseNotAllowed(["GET", "POST"]))
    page = MigrationPage()
    operation_id = request.POST.get("operation_id", request.GET.get("operation", ""))
    try:
        page.overview = service.status(actor=request.user)
        page.checked_at = timezone.now()
        if operation_id:
            page.operation = service.get_operation(operation_id, actor=request.user)
            if page.database.get("state") in {"unavailable", "incompatible"}:
                page.operation = {**page.operation, "can_retry": False, "can_abandon": False,
                    "recovery_reason": "Recovery actions are unavailable until the source database schema and access can be verified. Keep the database copies, backups and journals intact."}
        if request.method == "POST":
            response = perform(request, page)
            if response is not None:
                return prevent_private_response_caching(response)
    except TransferError as error:
        page.action_error, page.status_code = str(error), _error_status(error)
        page.feedback = busy_context(error)
    response = render(request, "admin/migrations.html", page_context(request, page), status=page.status_code)
    return prevent_private_response_caching(response)


def migration_status(request, operation_id):
    _authorize(request)
    if request.method != "GET":
        return prevent_private_response_caching(HttpResponseNotAllowed(["GET"]))
    try:
        operation = service.get_operation(operation_id, actor=request.user)
        data = {key: operation.get(key) for key in
            ("id", "status", "message", "error", "runner_active", "recoverable", "cancellable", "progress")}
        status = 200
    except TransferError as error:
        data, status = {"error": str(error)}, _error_status(error)
    return prevent_private_response_caching(JsonResponse(data, status=status))
