"""A small HTTP interface to the central, guarded database-copy manager."""

from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters

from qc_tool.database.transfers import service
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.authentication.maintenance import login_without_database_writes
from qc_tool.frontend.dashboard.forms.database_management import DeleteDatabaseForm
from qc_tool.frontend.dashboard.forms.data_transfers import DatabaseActivationForm
from qc_tool.frontend.dashboard.services.transfer_presentation import local_datetime
from qc_tool.frontend.dashboard.services.admin_feedback import busy_context
from qc_tool.frontend.dashboard.services.admin_overview import overview_context
from qc_tool.frontend.dashboard.services.database_navigation import database_page_context


def _url(**parameters):
    return reverse("admin_data_transfer") + "?" + urlencode({"tab": "databases", **parameters})


@sensitive_post_parameters("selection-password")
def database_manager(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])
    inventory, inspected, review = {}, None, None
    selection_form, deletion_form = None, None
    deletion_operation = ""
    error, status = "", 200
    action_feedback = {}
    target = request.POST.get("target_database", "")
    try:
        inventory = service.database_inventory(actor=request.user)
        if request.method == "POST":
            action = request.POST.get("action")
            if action in {"review_selection", "select_database"}:
                review = service.review_database_selection(target, actor=request.user)
                if action == "select_database":
                    selection_form = DatabaseActivationForm(
                        request.POST, prefix="selection", destination=review["target_database"],
                        requires_credentials=review.get("requires_credentials", False),
                    )
                    if selection_form.is_valid():
                        if not getattr(request, "_maintenance_cookie_session", False):
                            login_without_database_writes(request, request.user)
                        service.select_database(target, actor=request.user, **selection_form.cleaned_data)
                        messages.success(request, "Database selected. Maintenance stays on while you check it.")
                        response = HttpResponseRedirect(_url(), status=303)
                        response["Cache-Control"] = "no-store, private"
                        return response
                    status = 400
            elif action == "delete_database":
                deletion_operation = request.POST.get("operation_id", "")
                row = next((row for row in inventory.get("databases", [])
                            if row.get("operation_id") == deletion_operation), None)
                if not row:
                    raise service.TransferError("This database copy is not available. Reload the list.")
                deletion_form = DeleteDatabaseForm(request.POST, prefix="delete-" + deletion_operation, database=row["database"])
                if deletion_form.is_valid():
                    values = deletion_form.cleaned_data
                    service.delete_restore_database(deletion_operation, actor=request.user,
                        generation=values["generation"], revision=values["revision"],
                        destination_confirmation=values["destination_confirmation"])
                    messages.success(request, "Database copy deleted. Saved backup ZIPs and shared application files are kept.")
                    response = HttpResponseRedirect(_url(), status=303)
                    response["Cache-Control"] = "no-store, private"
                    return response
                status = 400
            else:
                error, status = "Choose an available database action.", 400
        if request.GET.get("inspect"):
            inspected = service.database_details(request.GET["inspect"], actor=request.user)
        if review and not selection_form and review.get("can_apply"):
            selection_form = DatabaseActivationForm(prefix="selection", destination=review["target_database"],
                requires_credentials=review.get("requires_credentials", False), initial={
                    "review_hash": review.get("review_hash"), "revision": review.get("revision"),
                    "generation": inventory.get("generation"),
                })
    except service.TransferError as problem:
        error = str(problem)
        action_feedback = busy_context(problem)
        status = getattr(problem, "status_code", 409)
        status = status if status in {400, 404, 409, 422, 503} else 409
    rows = []
    for row in inventory.get("databases", []):
        row = {**row, "created_local": local_datetime(row.get("created_at")),
               "exported_local": local_datetime((row.get("source_details") or {}).get("exported_at")),
               "inspect_url": _url(inspect=row["database"]) + "#database-inspection"}
        if row.get("operation_id"):
            row["restore_url"] = reverse("admin_data_transfer") + "?" + urlencode({"operation": row["operation_id"], "from": "databases"}) + "#transfer-operation"
            row["deletion_form"] = (deletion_form if row["operation_id"] == deletion_operation else
                DeleteDatabaseForm(database=row["database"], prefix="delete-" + row["operation_id"], initial={
                    "generation": inventory.get("generation"), "revision": inventory.get("revision")}))
            row["deletion_open"] = row["operation_id"] == deletion_operation
        rows.append(row)
    page_title = "Review database switch" if review else "Inspect database" if inspected else "Manage databases"
    page_description = ("Compare the current and selected databases before confirming which one everyone will use."
                        if review else "Check this database's compatibility and table inventory before deciding whether to use it."
                        if inspected else "Inspect databases on this server, switch the active database or remove an unused restore.")
    response = render(request, "admin/databases.html", {
        **action_feedback, "admin_busy_refresh_url": _url(),
        **admin.site.each_context(request), "is_nav_sidebar_enabled": False, "admin_section": "maintenance",
        **database_page_context("databases", title=page_title, description=page_description,
            child=bool(review or inspected), origin="databases", workspace="maintenance"),
        "transfer_task": "databases", "maintenance_url": reverse("admin_maintenance") + "?" + urlencode({"next": _url()}),
        "inventory": inventory, "database_copies": rows, "inspected_database": inspected,
        "inspected_copy": next((row for row in rows if inspected and row["database"] == inspected["database"]), None),
        "selection_review": review, "selection_form": selection_form, "target_database": target,
        "action_error": error,
        "database_overview": overview_context(request),
    }, status=status)
    response["Cache-Control"] = "no-store, private"
    return response
