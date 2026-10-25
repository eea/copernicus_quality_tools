"""Reviewed, administrator-only database packages and existing portable imports.

The HTTP layer never deserializes records or writes business data. The central
transfer service owns package validation, maintenance fencing and transactions.
"""

from django.contrib import admin, messages
import hashlib
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, HttpResponseNotAllowed, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from urllib.parse import urlencode

from qc_tool.database.transfers import downloads, service
from qc_tool.database.transfers.contracts import canonical_bytes
from qc_tool.database.transfers.components import EXPORT_COMPONENTS, EXPORT_COMPONENT_CHOICES, FILE_COMPONENTS
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.authentication.maintenance import login_without_database_writes
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.admin_feedback import busy_context
from qc_tool.frontend.dashboard.services.database_navigation import transfer_origin, transfer_workspace_context
from qc_tool.frontend.dashboard.services.transfer_presentation import backup_storage_summary, present_transfer, transfer_page_copy
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.forms.data_transfers import (
    AccountChoiceForm, AccountMappingForm, DatabaseActivationForm, DatabaseControlForm, ExportSelectionForm, ImportConfirmationForm,
    RecordResolutionForm, ReviewedActionForm, UploadPackageForm,
)


def _authorize(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied


def _operation_id(request):
    return request.POST.get("operation_id") or request.GET.get("operation") or ""


def _mapping_page(plan, request, page_number=None):
    accounts = plan.get("account_mappings", [])
    paginator = Paginator(accounts, 20)
    return paginator.get_page(page_number or request.POST.get("mapping_page") or request.GET.get("mapping_page") or 1)


def _account_choice_page(plan, request, page_number=None):
    return Paginator(plan.get("account_mappings", []), 20).get_page(
        page_number or request.POST.get("account_choice_page") or request.GET.get("account_choice_page") or 1)


def _conflict_page(plan, request, page_number=None):
    page = Paginator(plan.get("record_conflicts", []), 20).get_page(
        page_number or request.POST.get("conflict_page") or request.GET.get("conflict_page") or 1)
    page.object_list = [{**row, "impact_rows": _count_rows(row.get("impact")),
             "differences": [{**difference, "current": _difference_value(difference.get("current")),
                              "incoming": _difference_value(difference.get("incoming"))}
                             for difference in row.get("differences", [])],
             "resource_label": COUNT_LABELS.get(row.get("resource"), str(row.get("resource", "Records")).replace("_", " ").capitalize())}
            for row in page.object_list]
    return page


def _difference_value(value):
    """Bound presentation while retaining exact review evidence in the plan."""
    if isinstance(value, (dict, list)):
        encoded = canonical_bytes(value)
        kind = "object" if isinstance(value, dict) else "array"
        return f"JSON {kind} · {len(encoded):,} bytes · SHA-256 {hashlib.sha256(encoded).hexdigest()}"
    if isinstance(value, str) and len(value) > 240:
        checksum = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"{value[:160]}… ({len(value):,} characters; SHA-256 {checksum})"
    return value


def _resolutions(plan):
    """Keep saved decisions even when skipping dependencies hides their rows."""
    resolutions = dict(plan.get("resolutions") or {})
    for conflict in plan.get("record_conflicts", []):
        if conflict.get("resolution") in {"skip", "reuse"}:
            resolutions[conflict["key"]] = conflict["resolution"]
    return resolutions


FILE_STATUS_LABELS = {
    "packaged": "Included in package", "retained_verified": "Already on server — verified",
    "historical_absent": "Historical file unavailable", "remote": "Remote storage",
    "unverified_history": "Historical job input not verified", "missing": "Missing file",
    "different": "Different file on server",
    "not_included": "Not included — link retained", "unverified": "File not verified",
}


COUNT_LABELS = {
    "tables": "Database tables", "records": "Database records",
    "accounts": "User accounts", "products": "Products", "definitions": "QC definitions",
    "releases": "Product releases", "release_definitions": "Release definitions",
    "units": "Product units", "remote_sources": "Remote storage locations",
    "deliveries": "Deliveries", "jobs": "QC jobs", "submissions": "Submissions",
    "conflicts": "Submission conflicts", "conflict_events": "Conflict history",
    "review_events": "Review history",
}


def _count_rows(counts):
    return [(COUNT_LABELS.get(name, name.replace("_", " ").capitalize()), count)
            for name, count in (counts or {}).items() if count]


def _requested_task(request, default="start"):
    """Keep old bookmarks within the current Maintenance task hierarchy."""
    tab = request.GET.get("tab")
    if tab in {"history", "transfers"}:
        return "backups"
    if tab in {"import", "backups", "activity", "databases"}:
        return tab
    if tab in {"export", "backup"} or request.GET.get("scope"):
        return "export"
    return default


AREA_LABELS = {"users": "Users", "records": "Database records", "recovery": "Database packages"}
PROFILE_AREAS = {"accounts": "users", "application": "records", "database": "recovery"}


def _transfer_url(task=None, **parameters):
    if task in {"export", "import"}:
        url = reverse("admin_backup_export" if task == "export" else "admin_backup_import")
        return url + ("?" + urlencode(parameters, doseq=True) if parameters else "")
    query = {"tab": task} if task else {}
    query.update(parameters)
    return reverse("admin_data_transfer") + ("?" + urlencode(query, doseq=True) if query else "")


def _export_initial(request):
    # A marker distinguishes an explicitly empty section selection from the
    # all-sections default when following edit/maintenance links.
    components = (request.GET.getlist("components")
                  if "components_selected" in request.GET or "components" in request.GET
                  else list(EXPORT_COMPONENTS))
    return {"scope": "database", "components": components}


def _component_selection_parameters(selection):
    return {"components_selected": "true", "components": selection["components"]}


TASK_COPY = {
    "export": ("Create a backup", "Choose what to include, then review and download your ZIP."),
    "import": ("Restore from ZIP", "Upload a backup ZIP, review it and restore its contents."),
}


def _transfer_task(active_tab, operation):
    return operation["kind"] if operation else active_tab


def _error_status(error):
    status = getattr(error, "status_code", 409)
    return status if status in {400, 404, 409, 413, 422, 503} else 409


def _profile(operation):
    return (operation.get("profile") or (operation.get("plan") or {}).get("profile")
            or (operation.get("selection") or {}).get("profile") or "accounts")


def _require_profile_available(profile, schema_status, database_status):
    status = database_status if profile == "database" else schema_status
    if not status["ready"]:
        raise service.TransferError(status["message"])


def _source_details(value):
    details = (value or {}).get("source_details") or {}
    labels = {
        "app_version": "QC Tool version", "postgresql_version": "PostgreSQL version",
        "exported_at": "Exported", "source_database": "Source database",
    }
    return [(label, details[key]) for key, label in labels.items()
            if isinstance(details, dict) and isinstance(details.get(key), (str, int))
            and len(str(details[key])) <= 512]


def _compatibility_details(plan):
    compatibility = (plan or {}).get("compatibility")
    if not isinstance(compatibility, dict):
        return {}
    changes = []
    for change in compatibility.get("changes", [])[:200]:
        if not isinstance(change, dict):
            continue
        changes.append({
            "label": str(change.get("kind", "contract_changed")).replace("_", " ").capitalize()[:100],
            "path": str(change.get("path", "Package contract"))[:512],
            "source": _difference_value(change.get("source")),
            "target": _difference_value(change.get("target")),
        })
    count = compatibility.get("change_count")
    return {**compatibility, "changes": changes,
            "change_count": count if type(count) is int and count >= 0 else len(changes)}


@sensitive_post_parameters("activation-password", "rollback-password")
def data_transfer(request, default_task="start", workflow=None):
    """Selection → validation → review → durable asynchronous operation."""
    _authorize(request)
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    requested_task = workflow or _requested_task(request, default_task)
    if requested_task == "databases":
        from .admin_databases import database_manager
        return database_manager(request)

    if (request.method == "GET" and requested_task == "start"
            and not _operation_id(request) and request.GET.get("tab") != "transfers"):
        from .admin_database import database_home
        return database_home(request)

    if workflow and request.method == "POST":
        export_actions = {"preview_export", "export", "release_package", "retry", "cancel"}
        import_actions = {"upload", "review_database_switch", "activate_database", "rollback_database",
                          "prepare_destination", "plan", "revalidate", "resolve_conflicts", "apply", "retry", "cancel"}
        if request.POST.get("action") not in (export_actions if workflow == "export" else import_actions):
            return HttpResponseBadRequest("Choose an action from this page.")
    # Old backup/history bookmarks now open the export workspace, rather than
    # a third page combining unrelated creation, restoration and database tools.
    if requested_task in {"start", "backups", "activity"}:
        requested_task = "export"

    schema_status = service.schema_readiness()
    database_status = service.database_availability()
    export_form = ExportSelectionForm(initial=_export_initial(request))
    upload_form = UploadPackageForm()
    export_review = None
    operation = None
    plan = None
    mapping_form = None
    mapping_page = None
    mapping_page_number = None
    account_choice_form = None
    account_choice_page = None
    account_choice_page_number = None
    resolution_form = None
    conflict_page = None
    conflict_page_number = None
    confirmation_form = None
    activation_form = None
    activation_review = None
    rollback_form = None
    database_control = {}
    recent_operations = []
    backup_storage = None
    action_error = ""
    action_feedback = {}
    action_result = ""
    response_status = 200
    active_tab = requested_task
    try:
        maintenance_status = maintenance.read_status()
    except maintenance.MaintenanceError as error:
        maintenance_status = {"phase": "unavailable", "enabled": True, "generation": None}
        action_error = str(error)
        response_status = 503

    try:
        database_control = service.database_control_status(actor=request.user)
        operation_id = _operation_id(request)
        if operation_id:
            operation = service.get_operation(operation_id, actor=request.user)
            if workflow and operation["kind"] != workflow:
                if request.method == "POST":
                    return HttpResponseBadRequest("Open this task from its own import or export page.")
                return HttpResponseRedirect(_transfer_url(
                    task=operation["kind"], operation=operation["id"], **{"from": transfer_origin(request)},
                ) + "#transfer-operation")
            plan = operation.get("plan")
            active_tab = operation["kind"]
        if request.method == "POST":
            action = request.POST.get("action")
            if action in {"preview_export", "export"}:
                active_tab = "export"
                export_form = ExportSelectionForm(request.POST)
                if export_form.is_valid():
                    selection = export_form.selection()
                    _require_profile_available(selection["profile"], schema_status, database_status)
                    if action == "preview_export":
                        export_review = service.export_preview(selection, actor=request.user)
                    else:
                        reviewed_action = ReviewedActionForm(request.POST)
                        if reviewed_action.is_valid():
                            operation = service.create_export(
                                selection, actor=request.user,
                                reviewed_hash=reviewed_action.cleaned_data["reviewed_hash"],
                                generation=reviewed_action.cleaned_data["generation"],
                            )
                            # Preparation belongs to the detached runner. Land on
                            # a durable GET immediately, so reload/back cannot
                            # resubmit creation of this export.
                            redirect_parameters = {"operation": operation["id"]}
                            if request.GET.get("from") in {"activity", "backups"}:
                                redirect_parameters["from"] = transfer_origin(request)
                            response = HttpResponseRedirect(
                                _transfer_url(task="export", **redirect_parameters) + "#transfer-operation", status=303,
                            )
                            response["Cache-Control"] = "no-store, private"
                            return response
                        else:
                            action_error = "Review the export again before creating the file."
                            response_status = 400
                else:
                    response_status = 400
            elif action == "upload":
                active_tab = "import"
                if not schema_status["ready"] and not database_status["ready"]:
                    raise service.TransferError(schema_status["message"])
                upload_form = UploadPackageForm(request.POST, request.FILES)
                if upload_form.is_valid():
                    import_options = {}
                    if upload_form.cleaned_data["include_files"] is not None:
                        import_options["include_files"] = upload_form.cleaned_data["include_files"]
                    operation = service.stage_import(upload_form.cleaned_data["package"], actor=request.user,
                                                     **import_options)
                    if maintenance_status.get("phase") == "ready":
                        _require_profile_available(_profile(operation), schema_status, database_status)
                        plan = service.plan_import(operation["id"], actor=request.user)
                        operation = service.get_operation(operation["id"], actor=request.user)
                        action_result = "File checked. Review the detected package type and destination below."
                    else:
                        action_result = "File uploaded. Enable maintenance to check the detected package destination."
                else:
                    response_status = 400
            elif action == "review_database_switch" and operation:
                if (_profile(operation) != "database" or operation.get("kind") != "import"
                        or operation.get("status") != "completed"):
                    raise service.TransferError("Complete and verify a full database restore before switching.")
                if maintenance_status.get("phase") != "ready":
                    raise service.TransferError("Enable maintenance and confirm readiness before switching databases.")
                activation_review = service.activation_preview(operation["id"], actor=request.user)
                action_result = "Database switch checked. Review the destination and matching files before switching."
            elif action == "activate_database" and operation:
                if (_profile(operation) != "database" or operation.get("kind") != "import"
                        or operation.get("status") != "completed"):
                    raise service.TransferError("Complete and verify a full database restore before switching.")
                activation_review = service.activation_preview(operation["id"], actor=request.user)
                activation_form = DatabaseActivationForm(
                    request.POST, prefix="activation", destination=activation_review.get("target_database", ""),
                    requires_credentials=activation_review.get("requires_credentials", False),
                )
                if activation_form.is_valid():
                    if maintenance_status.get("phase") != "ready":
                        raise service.TransferError("Enable maintenance and confirm readiness before switching databases.")
                    if not getattr(request, "_maintenance_cookie_session", False):
                        login_without_database_writes(request, request.user)
                    service.activate_database(operation["id"], actor=request.user,
                        **{key: activation_form.cleaned_data[key] for key in (
                            "review_hash", "generation", "revision", "destination_confirmation",
                            "confirmed_storage", "username", "password")})
                    action_result = "Database switched. Maintenance remains on; the previous database is retained."
                else:
                    response_status = 400
            elif action == "rollback_database":
                rollback_form = DatabaseControlForm(
                    request.POST, prefix="rollback", destination=database_control.get("previous_database", ""),
                    requires_credentials=database_control.get("rollback_requires_credentials", False),
                )
                if rollback_form.is_valid():
                    if maintenance_status.get("phase") != "ready":
                        raise service.TransferError("Enable maintenance and confirm readiness before switching databases.")
                    if not getattr(request, "_maintenance_cookie_session", False):
                        login_without_database_writes(request, request.user)
                    service.rollback_database(actor=request.user,
                        **{key: rollback_form.cleaned_data[key] for key in (
                            "generation", "revision", "destination_confirmation", "confirmed_storage",
                            "username", "password")})
                    action_result = "Switched back to the previous database. Maintenance remains on."
                else:
                    response_status = 400
            elif action == "prepare_destination" and operation:
                if (_profile(operation) != "database" or operation.get("kind") != "import"
                        or operation.get("status") not in {"staged", "planned"}):
                    raise service.TransferError("Choose an uploaded full database backup before preparing a destination.")
                _require_profile_available("database", schema_status, database_status)
                if not operation.get("destination") and not database_status.get("can_create_restore_database"):
                    raise service.TransferError(database_status.get("restore_reason") or
                        "PostgreSQL permissions do not allow creating a restore database. An operator must enable database creation for this installation.")
                service.prepare_restore_destination(operation["id"], actor=request.user)
                operation = service.get_operation(operation["id"], actor=request.user)
                plan = operation.get("plan")
                action_result = "Fresh destination prepared. Review its name and confirm the restore."
            elif action in {"plan", "revalidate", "resolve_conflicts", "apply"} and operation and operation.get("kind") == "import":
                _require_profile_available(_profile(operation), schema_status, database_status)
                plan = operation.get("plan")
                if action == "revalidate" or (action == "plan" and (not plan or _profile(operation) == "database")):
                    plan = service.plan_import(operation["id"], actor=request.user)
                    operation = service.get_operation(operation["id"], actor=request.user)
                    action_result = "Destination checked. Review the import below."
                elif action in {"plan", "resolve_conflicts"} and plan:
                    changes = {}
                    choices_valid = True
                    if "account_choice_page" in request.POST:
                        if plan.get("profile") != "accounts" or "account_choices" not in plan:
                            raise service.TransferError("User choices are available only for user-profile imports.")
                        account_choice_page = _account_choice_page(plan, request)
                        account_choice_form = AccountChoiceForm(
                            request.POST, accounts=list(account_choice_page), plan_hash=plan.get("plan_hash"),
                        )
                        if account_choice_form.is_valid():
                            changes["account_choices"] = account_choice_form.choices(plan.get("account_choices"))
                            account_choice_page_number = request.POST.get("account_choice_page_next") or account_choice_page.number
                        else:
                            choices_valid = False
                    elif action == "plan" or "mapping_page" in request.POST:
                        mapping_page = _mapping_page(plan, request)
                        mapping_form = AccountMappingForm(request.POST, accounts=list(mapping_page), profile=plan.get("profile"))
                        if mapping_form.is_valid():
                            mappings = {str(account["source_id"]): account.get("target_id") for account in plan.get("account_mappings", [])}
                            mappings.update(mapping_form.mappings())
                            changes["mappings"] = mappings
                            mapping_page_number = request.POST.get("mapping_page_next") or mapping_page.number
                        else:
                            choices_valid = False
                    if action == "resolve_conflicts" or "conflict_page" in request.POST:
                        if plan.get("mode") != "additive" or plan.get("profile") != "application":
                            raise service.TransferError("Record conflict choices are available only for additive QC record imports.")
                        conflict_page = _conflict_page(plan, request)
                        resolution_form = RecordResolutionForm(
                            request.POST, conflicts=list(conflict_page), plan_hash=plan.get("plan_hash"),
                        )
                        if resolution_form.is_valid():
                            changes["resolutions"] = resolution_form.resolutions(_resolutions(plan))
                            conflict_page_number = request.POST.get("conflict_page_next") or conflict_page.number
                        else:
                            choices_valid = False
                    if choices_valid:
                        plan = service.plan_import(operation["id"], actor=request.user,
                                                   expected_plan_hash=plan.get("plan_hash"), **changes)
                        operation = service.get_operation(operation["id"], actor=request.user)
                        action_result = ("User choices saved. Review the selected additions and profile updates."
                                         if "account_choices" in changes else
                                         "Import choices saved. Review the updated additions and delivery files."
                                         if "resolutions" in changes else "Account mappings saved.")
                        mapping_form = None
                        account_choice_form = None
                        resolution_form = None
                    else:
                        response_status = 400
                elif plan:
                    ready_to_confirm = True
                    changes = {}
                    if "account_choice_page" in request.POST:
                        if plan.get("profile") != "accounts" or "account_choices" not in plan:
                            raise service.TransferError("User choices are available only for user-profile imports.")
                        account_choice_page = _account_choice_page(plan, request)
                        account_choice_form = AccountChoiceForm(
                            request.POST, accounts=list(account_choice_page), plan_hash=plan.get("plan_hash"),
                        )
                        if not account_choice_form.is_valid():
                            response_status = 400
                            ready_to_confirm = False
                        else:
                            posted_choices = account_choice_form.choices(plan.get("account_choices"))
                            if posted_choices != plan.get("account_choices"):
                                changes["account_choices"] = posted_choices
                    elif plan.get("profile") != "database" and "mapping_page" in request.POST:
                        mapping_page = _mapping_page(plan, request)
                        mapping_form = AccountMappingForm(request.POST, accounts=list(mapping_page), profile=plan.get("profile"))
                        if not mapping_form.is_valid():
                            response_status = 400
                            ready_to_confirm = False
                        else:
                            mappings = {str(account["source_id"]): account.get("target_id") for account in plan.get("account_mappings", [])}
                            posted = mapping_form.mappings()
                            if any(mappings.get(key) != value for key, value in posted.items()):
                                mappings.update(posted)
                                changes["mappings"] = mappings
                    if plan.get("mode") == "additive" and "conflict_page" in request.POST:
                        conflict_page = _conflict_page(plan, request)
                        resolution_form = RecordResolutionForm(
                            request.POST, conflicts=list(conflict_page), plan_hash=plan.get("plan_hash"),
                        )
                        if not resolution_form.is_valid():
                            response_status = 400
                            ready_to_confirm = False
                        else:
                            existing = _resolutions(plan)
                            posted = resolution_form.resolutions(existing)
                            if posted != existing:
                                changes["resolutions"] = posted
                    if changes and ready_to_confirm:
                        plan = service.plan_import(operation["id"], actor=request.user,
                                                   expected_plan_hash=plan.get("plan_hash"), **changes)
                        operation = service.get_operation(operation["id"], actor=request.user)
                        action_result = ("Import choices changed. Review and confirm the updated import."
                                         if "resolutions" in changes else "Account selections changed. Review and confirm the updated import.")
                        mapping_form = None
                        account_choice_form = None
                        resolution_form = None
                        ready_to_confirm = False
                    if ready_to_confirm:
                        confirmation_form = ImportConfirmationForm(
                            request.POST, confirmation_text=plan.get("confirmation_text") or plan.get("target_label", ""),
                            profile=plan.get("profile"),
                        )
                        if confirmation_form.is_valid():
                            operation = service.start_import(
                                operation["id"], actor=request.user,
                                plan_hash=confirmation_form.cleaned_data["plan_hash"],
                                generation=confirmation_form.cleaned_data["generation"],
                                confirmed_scope=confirmation_form.cleaned_data["confirmed_scope"],
                            )
                            action_result = "Database restore started." if plan.get("profile") == "database" else "Import started."
                        else:
                            response_status = 400
                else:
                    action_error = "Check the destination and review the records before importing."
                    response_status = 400
            elif action == "release_package" and operation:
                if operation.get("kind") != "export" or operation.get("status") != "completed":
                    raise service.TransferError("Only a completed export package can be released.")
                if request.POST.get("confirmed_release") != "on":
                    raise service.TransferError("Confirm that a verified copy is stored elsewhere before releasing this package.")
                operation = service.release_export_package(operation["id"], actor=request.user)
                plan = operation.get("plan")
                action_result = "Export package released. Transfer history is retained."
                if request.POST.get("return_to_backup_files") == "on":
                    messages.success(request, "Saved backup ZIP deleted. Databases and original files are unchanged.")
                    response = HttpResponseRedirect(_transfer_url(task="export") + "#prepared-backups", status=303)
                    response["Cache-Control"] = "no-store, private"
                    return response
            elif action in {"retry", "cancel"} and operation:
                operation = service.recover_operation(operation["id"], actor=request.user, action=action)
                plan = operation.get("plan")
                action_result = "Checking the interrupted transfer." if action == "retry" else "Transfer cancelled."
            else:
                action_error = "Choose a valid transfer action."
                response_status = 400
    except service.TransferError as error:
        action_error = str(error)
        action_feedback = busy_context(error)
        response_status = _error_status(error)
        # Enqueue/recovery may have persisted a newer state before its runner
        # failed. Keep the next action tied to that state instead of an old form.
        if operation:
            try:
                operation = service.get_operation(operation["id"], actor=request.user)
                plan = operation.get("plan")
            except service.TransferError:
                pass

    try:
        if active_tab == "export" and not operation and not export_review:
            stored_operations = service.list_operations(actor=request.user, limit=None, include_storage=True)
            recent_operations = stored_operations
            backup_storage = backup_storage_summary(stored_operations)
            try:
                backup_storage["capacity"] = service.backup_storage_capacity(actor=request.user)
            except service.TransferError as error:
                backup_storage["capacity_error"] = str(error)
        else:
            recent_operations = service.list_operations(actor=request.user)
    except service.TransferError as error:
        if not action_error:
            action_error = str(error)
            response_status = _error_status(error)
    if operation:
        plan = plan or operation.get("plan")
    try:
        if request.method == "POST" and request.POST.get("action") in {"activate_database", "rollback_database"}:
            database_control = service.database_control_status(actor=request.user)
        if activation_review:
            activation_form = activation_form or DatabaseActivationForm(
                prefix="activation", destination=activation_review.get("target_database", ""),
                requires_credentials=activation_review.get("requires_credentials", False),
                initial={"review_hash": activation_review.get("review_hash"),
                         "revision": activation_review.get("revision"), "generation": maintenance_status.get("generation")},
            )
        if database_control.get("previous_database"):
            rollback_form = rollback_form or DatabaseControlForm(
                prefix="rollback", destination=database_control["previous_database"],
                requires_credentials=database_control.get("rollback_requires_credentials", False),
                initial={"revision": database_control.get("revision"), "generation": maintenance_status.get("generation")},
            )
    except service.TransferError as error:
        if not action_error:
            action_error = str(error)
            response_status = _error_status(error)
    if (plan and operation and operation.get("kind") == "import"
            and operation.get("status") in {"staged", "planned"}):
        if plan.get("profile") == "accounts" and "account_choices" in plan:
            account_choice_page = _account_choice_page(plan, request, account_choice_page_number)
            account_choice_form = account_choice_form or AccountChoiceForm(
                accounts=list(account_choice_page), plan_hash=plan.get("plan_hash"),
            )
        elif plan.get("profile") != "database":
            mapping_page = _mapping_page(plan, request, mapping_page_number)
            mapping_form = mapping_form or AccountMappingForm(accounts=list(mapping_page), profile=plan.get("profile"))
        if plan.get("mode") == "additive":
            conflict_page = _conflict_page(plan, request, conflict_page_number)
            resolution_form = resolution_form or RecordResolutionForm(
                conflicts=list(conflict_page), plan_hash=plan.get("plan_hash"),
            )
        confirmation_form = confirmation_form or ImportConfirmationForm(
            confirmation_text=plan.get("confirmation_text") or plan.get("target_label", ""),
            profile=plan.get("profile"),
            initial={"plan_hash": plan.get("plan_hash"), "generation": maintenance_status.get("generation")},
        )
    try:
        transfer_operation = active_operation()
    except maintenance.MaintenanceError as error:
        transfer_operation = {"kind": "unavailable", "operation_id": ""}
        if not action_error:
            action_error = str(error)
            response_status = 503
    current_transfer = None
    if transfer_operation:
        current_transfer = next((item for item in [operation, *recent_operations]
            if item and item.get("id") == transfer_operation.get("operation_id")), None)
    result = (operation or {}).get("result") or {}
    created_accounts = len(result.get("created_account_keys", []))
    mapped_accounts = max(0, len(result.get("user_mappings", {})) - created_accounts)
    export_selection = None
    export_scope_label = ""
    transfer_area = PROFILE_AREAS[_profile(operation)] if operation else "recovery"
    initial_selection = _export_initial(request)
    selected_components = (export_form.cleaned_data.get("components", initial_selection["components"])
                           if export_form.is_bound else initial_selection["components"])
    edit_parameters = _component_selection_parameters({"components": selected_components})
    if request.GET.get("from") in {"activity", "backups", "databases"}:
        edit_parameters["from"] = transfer_origin(request)
    if export_review:
        selection = export_form.selection()
        export_selection = {"scope": "database", "user_ids": [],
                            "components": selection["components"],
                            "include_files": bool(set(selection["components"]) & set(FILE_COMPONENTS))}
        export_scope_label = "Complete database: schema and every record"
    edit_export_url = _transfer_url(task="export", **edit_parameters)
    transfer_task = _transfer_task(active_tab, operation)
    return_parameters = {}
    if operation:
        return_parameters["operation"] = operation["id"]
    elif transfer_task == "export":
        return_parameters.update(edit_parameters)
    origin = transfer_origin(request)
    if operation or transfer_task in {"export", "import"}:
        return_parameters["from"] = origin
    return_url = _transfer_url(task=transfer_task, **return_parameters)
    maintenance_url = reverse("admin_maintenance") + "?" + urlencode({"next": return_url})
    account_blockers = {
        f"Account {row['username']}: {row['blocker']}"
        for row in (plan or {}).get("account_mappings", []) if row.get("blocker")
    }
    maintenance_ready = maintenance_status.get("phase") == "ready" and not transfer_operation
    database_backup_ready = database_status["ready"] and maintenance_ready
    database_restore_ready = database_backup_ready
    portable_ready = schema_status["ready"] and maintenance_ready
    native_transfer = (_profile(operation) == "database" if operation else
                       transfer_task == "export")
    native_import = bool(native_transfer and operation and operation.get("kind") == "import")
    additive_import = bool(operation and operation.get("kind") == "import" and
                           (plan or {}).get("mode") == "additive")
    file_rows = [{**row, "status_label": FILE_STATUS_LABELS.get(row.get("status"), "File needs review"),
                  "file_status_label": FILE_STATUS_LABELS.get(row.get("file_status"), "")}
                 for row in (plan or {}).get("delivery_files", [])]
    file_page = Paginator(file_rows, 20).get_page(request.GET.get("file_page") or 1)
    operation_database = (((operation or {}).get("destination") or {}).get("database")
                          or result.get("target_database") or (activation_review or {}).get("target_database"))
    needs_native_destination = bool(native_import and operation.get("status") in {"staged", "planned"}
                                    and not operation.get("destination"))
    native_restore_step = ("prepare" if needs_native_destination else
                           "verify" if operation and operation.get("status") == "completed" else "restore")
    operation_database_active = bool(native_import and operation_database
                                     and operation_database == database_control.get("active_database"))
    can_review_database_switch = bool(native_import and operation.get("status") == "completed"
                                      and result.get("verified")
                                      and not operation_database_active and maintenance_ready
                                      and not operation.get("database_deleted_at")
                                      and not operation.get("database_deletion_requested_at"))
    transfer_ready = (database_restore_ready if operation and operation["kind"] == "import" else database_backup_ready) if native_transfer else portable_ready
    task_title, task_description = TASK_COPY[transfer_task]
    if operation:
        task_title, task_description = transfer_page_copy(operation, native_import=native_import,
            needs_destination=needs_native_destination, database_active=operation_database_active,
            switch_review=bool(activation_review))
    elif export_review:
        task_title, task_description = "Review backup contents", "Check the selected sections and storage estimate, then create the backup ZIP."
    context = {
        **action_feedback,
        "admin_busy_refresh_url": return_url,
        **admin.site.each_context(request),
        "is_nav_sidebar_enabled": False,
        "title": task_title, "active_tab": active_tab, "export_form": export_form,
        "transfer_task": transfer_task, "transfer_task_title": task_title,
        "export_workflow": transfer_task == "export",
        "transfer_task_description": task_description,
        "transfer_area": transfer_area, "transfer_area_label": AREA_LABELS[transfer_area],
        "admin_section": "maintenance",
        **transfer_workspace_context(transfer_task, title=task_title, description=task_description, operation=bool(operation)),
        "transfer_action_url": _transfer_url(task=transfer_task, **{"from": origin}),
        "transfer_origin": origin,
        "operation_refresh_url": (_transfer_url(task=transfer_task, operation=operation["id"], **{"from": origin})
                                  + "#transfer-operation") if operation else "",
        "export_component_rows": [(label, key in selected_components) for key, label in EXPORT_COMPONENT_CHOICES],
        "export_omitted_components": [label for key, label in EXPORT_COMPONENT_CHOICES if key not in selected_components],
        "export_selection": export_selection, "export_scope_label": export_scope_label,
        "edit_export_url": edit_export_url, "maintenance_url": maintenance_url,
        "export_counts": _count_rows((export_review or {}).get("counts")),
        "plan_counts": _count_rows((plan or {}).get("counts")),
        "result_count_rows": _count_rows(result.get("created_counts") or result.get("counts")),
        "plan_global_blockers": [message for message in (plan or {}).get("blockers", []) if message not in account_blockers],
        "account_blocker_count": len(account_blockers),
        "upload_form": upload_form, "export_review": export_review,
        "operation": present_transfer(operation), "plan": plan, "mapping_form": mapping_form,
        "mapping_page": mapping_page,
        "account_choice_form": account_choice_form, "account_choice_page": account_choice_page,
        "account_summary": (plan or {}).get("account_summary", {}),
        "resolution_form": resolution_form, "conflict_page": conflict_page,
        "additive_import": additive_import, "delivery_file_page": file_page,
        "additive_review_step": "resolve" if account_blockers or ((plan or {}).get("record_conflicts") and (plan or {}).get("blockers")) else "review",
        "confirmation_form": confirmation_form, "transfer_maintenance": maintenance_status,
        "transfer_schema": schema_status,
        "transfer_database": database_status, "native_transfer": native_transfer,
        "native_import": native_import, "needs_native_destination": needs_native_destination,
        "native_restore_step": native_restore_step,
        "database_control": database_control, "activation_review": activation_review,
        "activation_form": activation_form, "rollback_form": rollback_form,
        "operation_database_active": operation_database_active,
        "operation_database": operation_database,
        "can_review_database_switch": can_review_database_switch,
        "can_prepare_native_destination": bool(needs_native_destination and database_restore_ready
                                               and database_status.get("can_create_restore_database")),
        "source_details": _source_details(plan or export_review or operation),
        "transfer_compatibility": _compatibility_details(plan),
        "database_backup_ready": database_backup_ready, "database_restore_ready": database_restore_ready,
        "portable_ready": portable_ready,
        "export_available": maintenance_ready and (schema_status["ready"] or database_status["ready"]),
        "upload_available": (schema_status["ready"] or database_status["ready"]) and not transfer_operation,
        "action_error": action_error, "action_result": action_result,
        "maintenance_ready": maintenance_ready,
        "transfers_ready": transfer_ready,
        "transfer_operation": transfer_operation,
        "current_transfer": current_transfer,
        "recent_operations": [present_transfer(item) for item in recent_operations],
        "backup_storage": backup_storage,
        "prepared_backups": [item for item in (backup_storage or {}).get("saved_exports", [])
                             if item.get("downloadable") and item.get("saved_file_available")
                             and not item.get("package_release_requested_at")],
        "export_operations": [present_transfer(item) for item in recent_operations
                              if item.get("kind") == "export" and (
                                  item.get("status") in {"queued", "running", "recovery_required"}
                                  or item.get("recoverable")
                                  or (item.get("package_release_requested_at") and not item.get("payload_released_at")))],
        "import_operations": [present_transfer(item) for item in recent_operations if item.get("kind") == "import"],
        "can_review_import": bool(operation and operation.get("kind") == "import" and operation.get("status") in {"staged", "planned"}),
        "created_accounts": created_accounts, "mapped_accounts": mapped_accounts,
    }
    template = "admin/backup_export.html" if transfer_task == "export" else "admin/backup_import.html"
    response = render(request, template, context, status=response_status)
    response["Cache-Control"] = "no-store, private"
    return response


def data_transfer_status(request, operation_id):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        operation = service.get_operation(operation_id, actor=request.user)
    except service.TransferError as error:
        return JsonResponse({"error": str(error)}, status=_error_status(error))
    response = JsonResponse({
        key: operation.get(key) for key in
        ("id", "kind", "status", "message", "error", "created_at", "updated_at", "expires_at",
         "downloadable", "maintenance_owned", "runner_active", "recoverable", "cancellable", "progress")
    })
    response["Cache-Control"] = "no-store, private"
    return response


def data_transfer_download(request, operation_id):
    _authorize(request)
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])
    try:
        stream, metadata = service.download_operation(operation_id, actor=request.user)
    except service.TransferError as error:
        return JsonResponse({"error": str(error)}, status=_error_status(error))
    return downloads.response(stream, metadata, request)
