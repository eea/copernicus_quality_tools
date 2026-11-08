"""Compose migration page sections from service reports and the shared Admin shell."""

from django.contrib import admin
from django.urls import reverse

from qc_tool.frontend.dashboard.context_processors import maintenance_context
from qc_tool.frontend.dashboard.forms.migrations import MigrationPreparationForm, activation_form
from qc_tool.frontend.dashboard.services.admin_overview import overview_context
from qc_tool.frontend.dashboard.services.database_navigation import maintenance_task_urls
from qc_tool.frontend.dashboard.services.transfer_presentation import local_datetime

from .journey import next_step
from .presentation import initializes_history, migration_names, migration_rows, operation_database, present_operation, present_review
from .urls import maintenance_url, migration_url


def _confirmations(page):
    if page.review:
        page.review = present_review(page.review)
        if page.preparation_form is None and page.review.get("can_apply"):
            page.preparation_form = MigrationPreparationForm(initial={
                name: page.review.get(name) for name in ("backup_id", "review_hash", "generation", "revision")})
    if page.activation_review and page.activation_form is None and page.activation_review.get("can_apply"):
        page.activation_form = activation_form(page.activation_review,
            generation=page.overview.get("maintenance", {}).get("generation"))


def _maintenance_notice(request, page, current_operation, initializes):
    notice = maintenance_context(request)["maintenance"]
    if ((page.operation or {}).get("maintenance_owned") or current_operation.get("transfer_url")
            or current_operation.get("transfer_error")):
        notice.update(can_disable=False,
            resume_blocked_reason="Complete or recover the current database operation before turning maintenance off.")
    elif page.database.get("state") != "ready":
        notice.update(can_disable=False, resume_blocked_reason=(
            "Initialize Django migration history on a verified copy and select it before reopening." if initializes else
            "The active database is not ready for this installation. Finish the reviewed upgrade or investigate schema drift before reopening."))
    return notice


def page_context(request, page):
    _confirmations(page)
    overview, database = page.overview, page.database
    active_database = overview.get("active_database")
    operation = present_operation(page.operation, active_database) if page.operation else None
    destination = operation_database(operation)
    operation_active = bool(destination and destination == active_database)
    initializes = initializes_history(overview, operation)
    operation_id = operation["id"] if operation else ""
    phase = overview.get("maintenance", {}).get("phase", "unavailable")
    backups = [{**item, "created_local": local_datetime(item.get("created_at"))} for item in overview.get("backups", [])]
    current_operation = overview_context(request)
    step = next_step(page, operation_active=operation_active, current_operation=current_operation, backups=backups)
    source_label = overview.get("source_release")
    if database.get("state") not in {"legacy", "pending", "ready"}:
        source_label = "Not verified"
    elif source_label == "managed history":
        source_label = "Managed migration history"
    task_urls = maintenance_task_urls()
    destinations = {"maintenance": maintenance_url(operation_id), "export": task_urls["export_page_url"],
        "applied": "#migration-applied", "history": "#migration-history-heading", "help": "#migration-help",
        "review": "#migration-review-heading", "operation": "#migration-operation-heading", "backups": "#migration-backup-heading"}
    return {
        **admin.site.each_context(request), **task_urls, **page.feedback,
        "title": "Database migrations", "admin_section": "maintenance",
        "database_page_title": "Database migrations",
        "database_page_description": "Check database updates, review past migrations and safely apply changes shipped with QC Tool.",
        "database_breadcrumbs": [{"label": "Maintenance", "url": reverse("admin_maintenance")},
                                 {"label": "Database migrations", "url": ""}],
        "database_back_url": reverse("admin_maintenance"), "database_back_label": "Back to Maintenance",
        "hide_database_navigation": True,
        "migration_status": overview, "migration_database": database,
        "migration_database_state": {
            "legacy": "History-free v3.0.0; initialize Django migration history on a verified copy",
            "pending": "Installed migrations are available", "ready": "Up to date",
            "incompatible": "Schema or migration history needs investigation",
            "empty": "Empty database; initialization is required",
        }.get(database.get("state"), "Unavailable"),
        "migration_initializes_history": initializes, "migration_source_label": source_label or "Not recorded",
        "migration_checked_at": page.checked_at,
        "migration_blockers": list(dict.fromkeys([*overview.get("preparation_blockers", []),
                                                  *overview.get("blockers", []), *database.get("problems", [])])),
        "migration_maintenance_state": {"ready": "Ready — workers paused", "stopping": "Stopping work",
                                        "off": "Off", "unavailable": "Unavailable"}.get(phase, "Unavailable"),
        "migration_maintenance_ready": phase == "ready", "migration_can_prepare": bool(overview.get("can_prepare")),
        "migration_next_title": step.title, "migration_next_description": step.description,
        "migration_next_url": destinations.get(step.target, step.target), "migration_next_label": step.label,
        "migration_current_step": step.stage,
        "migration_show_preparation": (database.get("state") in {"legacy", "pending"}
            and not (page.review or {}).get("can_apply")
            and (not operation or operation_active or (operation.get("status") == "failed"
                                                       and not operation.get("maintenance_owned")))),
        "migration_applied_rows": migration_rows(database.get("applied_history", database.get("applied"))),
        "migration_pending_rows": migration_rows(database.get("pending")),
        "migration_health": {"ready": "Up to date", "legacy": "History initialization needed",
                             "pending": "Update available"}.get(database.get("state"), "Needs attention"),
        "migration_current_operation_url": current_operation.get("transfer_url"),
        "migration_source_unavailable": database.get("state") in {"unavailable", "incompatible"},
        "applied_names": migration_names(database.get("applied")), "pending_names": migration_names(database.get("pending")),
        "migration_backups": backups,
        "migration_operations": [present_operation(item, active_database) for item in overview.get("operations", [])],
        "migration_review": page.review, "preparation_form": page.preparation_form,
        "operation": operation, "operation_url": migration_url(operation_id),
        "operation_database": destination, "operation_active": operation_active,
        "activation_review": page.activation_review, "activation_form": page.activation_form,
        "maintenance_url": destinations["maintenance"], "action_error": page.action_error,
        "admin_busy_refresh_url": migration_url(operation_id),
        "maintenance": _maintenance_notice(request, page, current_operation, initializes),
    }
