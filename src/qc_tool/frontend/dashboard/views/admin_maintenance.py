"""Administrator controls for the application-wide maintenance barrier."""

from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.context_processors import MAINTENANCE_NOTICE
from qc_tool.frontend.dashboard.services import maintenance
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
            reverse("admin_data_transfer"), reverse("admin_user_management"),
            reverse("admin_storage"), reverse("admin_storage_file"), reverse("admin_storage_trash"),
        }
    ):
        return ""
    return value


def maintenance_control(request):
    """Keep state changes explicit, CSRF protected and administrator-only."""

    if not access_for_request(request).is_administrator:
        raise PermissionDenied
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    action_result = ""
    action_error = ""
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
                    maintenance.disable(
                        request.user, expected_generation=generation,
                    )
                    action_result = "Maintenance mode disabled. Users can submit new work."
                else:
                    action_error = "Choose a valid maintenance action."
                    response_status = 400
            except (maintenance.MaintenanceError, ValueError) as error:
                action_error = str(error)
                response_status = 409

    maintenance_unavailable = False
    transfer_operation = None
    try:
        status = maintenance.read_status()
        transfer_operation = active_operation()
    except maintenance.MaintenanceError as error:
        action_error = str(error)
        action_result = ""
        response_status = 503
        maintenance_unavailable = True
        status = {"enabled": True, "phase": "stopping", "blockers": []}
    request.maintenance_status = status
    request.maintenance_active = status["enabled"]
    progress_pending = (
        not maintenance_unavailable and not transfer_operation
        and status["enabled"] and status["phase"] == "stopping"
    )
    if request.method == "POST" and request.headers.get("Accept") == "application/json":
        response = JsonResponse({
            "phase": status["phase"],
            "generation": status.get("generation"),
            "poll": progress_pending,
            "blockers": status["blockers"],
            "error": action_error,
            "transfer_active": bool(transfer_operation),
        }, status=response_status)
        response["Cache-Control"] = "no-store, private"
        return response
    context = {
        **admin.site.each_context(request),
        "title": "Maintenance mode",
        "maintenance": {**status, "notice": MAINTENANCE_NOTICE},
        "deployment_maintenance": deployment_maintenance,
        "action_result": action_result,
        "action_error": action_error,
        "maintenance_unavailable": maintenance_unavailable,
        "transfer_operation": transfer_operation,
        "transfer_return_url": _transfer_return_url(request),
        "database_return": _transfer_return_url(request) == reverse("admin_data_transfer"),
        "storage_return": urlsplit(_transfer_return_url(request)).path in {
            reverse("admin_storage"), reverse("admin_storage_file"), reverse("admin_storage_trash"),
        },
        "progress_pending": progress_pending,
    }
    # Render the result directly: redirects/messages would introduce avoidable
    # session writes after the maintenance barrier has become ready.
    return render(
        request, "admin/maintenance.html", context, status=response_status,
    )
