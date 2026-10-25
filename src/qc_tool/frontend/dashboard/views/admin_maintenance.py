"""Administrator controls for the application-wide maintenance barrier."""

from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.context_processors import maintenance_context
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.admin_feedback import busy_context
from qc_tool.frontend.dashboard.services.database_navigation import maintenance_task_urls
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


def _transfer_return_url(request):
    """Keep the transfer workflow without accepting arbitrary return URLs."""

    value = request.POST.get("next", request.GET.get("next", ""))
    if (
        len(value) > 1024
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or parsed.path not in {
            reverse("admin_data_transfer"), reverse("admin_database"), reverse("admin_user_management"),
            reverse("admin_backup_export"), reverse("admin_backup_import"),
            reverse("admin_storage"), reverse("admin_storage_file"), reverse("admin_storage_trash"),
        }
    ):
        return ""
    return value


def _admin_return_url(request):
    """Return an Admin page after its explicit, shared maintenance-off form."""

    value = request.POST.get("next", "")
    fallback = reverse("admin:index")
    if (
        len(value) > 2048
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return fallback
    try:
        parsed = urlsplit(value)
    except ValueError:
        return fallback
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return fallback
    # reverse includes any deployment script prefix. Reject path encodings that
    # browsers, proxies or the server could normalize outside that Admin root.
    admin_root = reverse("admin:index")
    path = parsed.path
    for _ in range(3):
        if (
            not path.startswith(admin_root)
            or "\\" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
        ):
            return fallback
        decoded = unquote(path)
        if decoded == path:
            return value
        path = decoded
    return fallback


def maintenance_control(request):
    """Keep state changes explicit, CSRF protected and administrator-only."""

    if not (
        getattr(request.user, "is_active", False)
        and getattr(request.user, "is_staff", False)
        and access_for_request(request).is_administrator
    ):
        raise PermissionDenied
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    action_result = ""
    action_error = ""
    action_busy = False
    response_status = 200
    deployment_maintenance = bool(getattr(settings, "MAINTENANCE_MODE", False))
    if request.method == "POST":
        try:
            generation = int(request.POST.get("generation", ""))
            if generation < 0:
                raise ValueError
        except (TypeError, ValueError):
            action_error = "The maintenance state is missing. Reload this page and try again."
            response_status = 400
        else:
            try:
                action = request.POST.get("action")
                if action == "enable":
                    enabled = maintenance.enable(
                        request.user, expected_generation=generation,
                    )
                    maintenance.advance(expected_generation=enabled["generation"])
                    action_result = "Maintenance mode enabled."
                elif action == "advance":
                    maintenance.advance(expected_generation=generation)
                    action_result = "Worker status checked."
                elif action == "progress":
                    # Automatic progress must never revoke an already-ready
                    # barrier, even if another tab completed it in the meantime.
                    maintenance.advance(expected_generation=generation, stopping_only=True)
                elif action == "disable" and deployment_maintenance:
                    action_error = "Maintenance mode is enforced by the deployment configuration and cannot be disabled here."
                    response_status = 409
                elif action == "disable":
                    from qc_tool.database.transfers.service import validate_resume_database
                    validate_resume_database(request.user)
                    disabled = maintenance.disable(
                        request.user, expected_generation=generation,
                    )
                    if request.POST.get("return_to_page") == "1":
                        request.maintenance_status = disabled
                        request.maintenance_active = disabled["enabled"]
                        return redirect(_admin_return_url(request))
                    action_result = "Maintenance mode disabled. Users can submit new work."
                else:
                    action_error = "Choose a valid maintenance action."
                    response_status = 400
            except (maintenance.MaintenanceError, ValueError) as error:
                action_error = str(error)
                action_busy = bool(busy_context(error))
                response_status = 409

    maintenance_unavailable = False
    transfer_operation = None
    control_busy = False
    try:
        status = maintenance.read_status()
        transfer_operation = active_operation()
        if request.headers.get("Accept") == "application/json" or request.method == "GET":
            from qc_tool.database.transfers import store
            control_busy = maintenance.control_active() or store.execution_active()
    except (maintenance.MaintenanceError, TransferError) as error:
        action_error = str(error)
        action_result = ""
        response_status = 503
        maintenance_unavailable = True
        action_busy = False
        status = {"enabled": True, "phase": "stopping", "blockers": []}
    request.maintenance_status = status
    request.maintenance_active = status["enabled"]
    progress_pending = (
        not maintenance_unavailable and not transfer_operation
        and status["enabled"] and status["phase"] == "stopping"
    )
    if request.headers.get("Accept") == "application/json":
        response = JsonResponse({
            "phase": status["phase"],
            "generation": status.get("generation"),
            "poll": progress_pending if request.method == "POST" else progress_pending or control_busy,
            "blockers": status["blockers"],
            "error": action_error,
            "busy": action_busy or control_busy,
            "transfer_active": bool(transfer_operation),
            "transfer_url": (
                reverse("admin_data_transfer") + "?operation=" + transfer_operation["operation_id"]
                if transfer_operation else ""
            ),
        }, status=response_status)
        response["Cache-Control"] = "no-store, private"
        if action_busy or control_busy:
            response["Retry-After"] = "3"
        return response
    notice_context = maintenance_context(request)["maintenance"]
    if transfer_operation or action_busy or control_busy:
        notice_context["can_disable"] = False
        notice_context["resume_blocked_reason"] = (
            "A database transfer owns maintenance. Complete or recover it before turning maintenance off."
            if transfer_operation else
            "Another administrator action is still running. Wait for it to finish before turning maintenance off."
        )
    context = {
        **admin.site.each_context(request),
        **maintenance_task_urls(),
        "title": "Maintenance",
        "maintenance_page_description": "Turn maintenance on or off, create backups and restore saved ZIPs.",
        "admin_section": "maintenance",
        "maintenance": {
            **status, **notice_context,
            "phase": "unavailable" if maintenance_unavailable else status["phase"],
        },
        "deployment_maintenance": deployment_maintenance,
        "action_result": action_result,
        "action_error": action_error,
        "action_busy": action_busy,
        "control_busy": control_busy,
        "maintenance_busy_waiting": (action_busy or control_busy) and not progress_pending and not transfer_operation,
        "admin_busy_status_url": reverse("admin_maintenance"),
        "admin_busy_refresh_url": request.get_full_path(),
        "busy_message": action_error or "An administrator action is already using maintenance. Wait for it to finish before trying again.",
        "maintenance_unavailable": maintenance_unavailable,
        "transfer_operation": transfer_operation,
        "transfer_return_url": _transfer_return_url(request),
        "progress_pending": progress_pending,
    }
    # Render the result directly: redirects/messages would introduce avoidable
    # session writes after the maintenance barrier has become ready.
    return render(
        request, "admin/maintenance.html", context, status=response_status,
    )
