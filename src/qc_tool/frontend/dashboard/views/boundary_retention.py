"""Admin review, reversible removal and restoration of boundary versions."""

from urllib.parse import urlencode

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import reverse

from qc_tool.frontend.dashboard.services import boundary_retention as retention
from qc_tool.frontend.dashboard.services.maintenance import MaintenanceError, read_status
from qc_tool.frontend.dashboard.services.storage_admin.files import StorageError
from qc_tool.frontend.dashboard.services.storage_admin.versions import list_versions


def _context(request):
    context = {**admin.site.each_context(request), "title": "Retained boundary versions", "admin_section": "boundaries"}
    try:
        context["boundary_retention_reason"] = retention.removal_protection_reason()
    except StorageError as error:
        context["boundary_retention_reason"] = str(error)
    try:
        context["boundary_maintenance"] = read_status()
    except MaintenanceError as error:
        context["boundary_retention_reason"] = str(error)
    try:
        listing = list_versions("boundaries", status="all", page=request.GET.get("page", "1"))
        for entry in listing["entries"]:
            entry["review_url"] = reverse("boundaries_retention") + "?" + urlencode({"review": entry["version_id"]})
            entry["can_review_removal"] = entry["status"] == "previous" and not context["boundary_retention_reason"]
        context["boundary_versions"] = listing
    except StorageError as error:
        context["boundary_retention_error"] = str(error)
    context["boundary_trash"] = retention.list_trash(page=request.GET.get("trash_page", "1"))
    return context


def retained_boundaries(request):
    context = _context(request)
    if request.GET.get("review"):
        try:
            context["boundary_removal_review"] = retention.preview_removal(request.GET["review"], request.user)
        except StorageError as error:
            context["boundary_retention_error"] = str(error)
    return render(request, "admin/boundaries/retained.html", context)


def retained_boundary_action(request):
    try:
        try:
            generation = int(request.POST.get("maintenance_generation", ""))
        except (TypeError, ValueError) as error:
            raise StorageError("Maintenance changed. Reload and review this action.") from error
        action = request.POST.get("action")
        if action == "remove":
            result = retention.remove_generation(request.POST.get("generation_id"), request.user, generation,
                                                 request.POST.get("review_hash"))
        elif action == "restore":
            result = retention.restore_generation(request.POST.get("operation_id"), request.user, generation)
        else:
            raise StorageError("Choose a supported boundary action.", status_code=400)
    except StorageError as error:
        return render(request, "admin/boundaries/retained.html",
                      {**_context(request), "boundary_retention_error": str(error)}, status=error.status_code)
    messages.success(request, result["message"])
    return redirect("boundaries_retention")
