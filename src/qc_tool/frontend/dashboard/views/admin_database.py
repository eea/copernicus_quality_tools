"""Administrator record inspection. Writes use ordinary, guarded ModelAdmins."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.database_admin.presentation import (
    cell, dependencies, editor_actions, field_label, query_records, record_field_groups,
    record_heading, record_rows, table_url,
)
from qc_tool.frontend.dashboard.services.database_admin.resources import resource_for, resources
from qc_tool.frontend.dashboard.services.transfer_presentation import local_datetime
from qc_tool.frontend.dashboard.services.database_navigation import database_page_context, database_tables_url


def _authorize(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])


def _render(request, template, context, *, status=200):
    resource = context.get("resource")
    account_records = resource and (resource.category == "Accounts & access" or resource.table == "auth_permission")
    database_url = reverse("admin_database")
    records_home_url = reverse("admin_user_management") if account_records else database_tables_url()
    navigation = {}
    if resource:
        record_detail = "record_pk" in context
        heading = context.get("record_heading", resource.label)
        records_url = context.get("records_url", table_url(resource))
        if account_records:
            breadcrumbs = [{"label": "User management", "url": records_home_url}]
        else:
            navigation = database_page_context("tables", title=heading, description=resource.description)
            breadcrumbs = [{"label": "Database", "url": database_url},
                           {"label": "Tables & records", "url": records_home_url}]
        breadcrumbs.append({"label": resource.label, "url": records_url if record_detail else ""})
        if record_detail:
            breadcrumbs.append({"label": "Record " + str(context["record_pk"]), "url": ""})
        navigation.update({
            "database_breadcrumbs": breadcrumbs,
            "database_back_url": records_url if record_detail else records_home_url,
            "database_back_label": ("Back to " + resource.label if record_detail else
                                    "Back to user management" if account_records else "Back to tables"),
        })
    response = render(request, template, {
        **admin.site.each_context(request), "is_nav_sidebar_enabled": False,
        "admin_section": "users" if account_records else "database",
        "database_url": database_url, "transfers_url": reverse("admin_data_transfer") + "?tab=backups",
        "records_home_url": records_home_url,
        "records_home_label": "User management" if account_records else "Tables & records",
        "account_records": bool(account_records), **context, **navigation,
    }, status=status)
    response["Cache-Control"] = "no-store, private"
    return response


def _database_metadata():
    """Read public database identity without exposing connection credentials."""
    from django.db import connection
    from pathlib import Path

    metadata = {"name": Path(str(connection.settings_dict.get("NAME") or "")).name,
                "engine": connection.display_name, "version": "Unavailable", "schema": "Unavailable"}
    try:
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute("SELECT current_setting('server_version'), current_schema()")
                metadata["version"], metadata["schema"] = cursor.fetchone()
            elif connection.vendor == "sqlite":
                cursor.execute("SELECT sqlite_version()")
                metadata["version"] = cursor.fetchone()[0]
                metadata["schema"] = "main"
    except DatabaseError:
        pass
    return metadata


def database_home(request):
    denied = _authorize(request)
    if denied:
        return denied
    query = (request.GET.get("q") or "").strip()[:150]
    category = request.GET.get("category") or ""
    groups = {}
    inventory = resources()
    for resource in inventory:
        if query and query.casefold() not in (resource.label + " " + resource.table + " " + resource.description).casefold():
            continue
        if category and category != resource.category:
            continue
        groups.setdefault(resource.category, []).append({
            "resource": resource, "url": table_url(resource),
            "editable": bool(resource.editor or resource.create or resource.delete or resource.owner),
        })
    from qc_tool.database.policy import DatabasePolicyError, load_policy
    from qc_tool.database.transfers.service import schema_readiness
    try:
        policy = load_policy()
        policy_error = ""
    except DatabasePolicyError as error:
        policy, policy_error = {}, str(error)
    schema_status = schema_readiness()
    checked_at = schema_status.get("checked_at")
    from qc_tool.database.selection import current_database, DatabaseSelectionError
    try:
        active_database = current_database()
    except DatabaseSelectionError:
        active_database = ""
    records_mode = bool(query or category or request.GET.get("tables") == "1")
    return _render(request, "admin/database.html", {
        **database_page_context("tables" if records_mode else "overview", title="Tables & records" if records_mode else "Database",
            description=("Choose a table to browse its records."
                         if records_mode else
                         "Inspect the active database and its compatibility with QC Tool.")),
        "table_groups": groups.items(), "table_count": len(inventory),
        "matching_table_count": sum(len(tables) for tables in groups.values()),
        "categories": sorted({item.category for item in inventory}), "category": category, "query": query,
        "database_policy": policy, "database_policy_error": policy_error,
        "database_schema_status": schema_status,
        "active_database": active_database,
        "database_metadata": _database_metadata(),
        "database_schema_checked_at": local_datetime(checked_at),
        "records_mode": records_mode,
    })


def database_records(request, table):
    denied = _authorize(request)
    if denied:
        return denied
    resource = resource_for(table)
    if resource is None:
        raise Http404
    try:
        queryset, query = query_records(resource, request.GET)
        page = Paginator(queryset, 25).get_page(request.GET.get("page"))
        rows = record_rows(resource, page)
    except (ValidationError, ValueError, TypeError):
        raise Http404 from None
    except DatabaseError:
        return _render(request, "admin/database_records.html", {
            "title": resource.label, "resource": resource,
            "record_error": "These records could not be read. Check database availability and schema readiness before continuing.",
        }, status=503)
    parameters = request.GET.copy()
    parameters.pop("page", None)
    search_parameters = parameters.copy()
    search_parameters.pop("q", None)
    relation_parameters = parameters.copy()
    relation_parameters.pop("related_field", None)
    relation_parameters.pop("related_value", None)
    return _render(request, "admin/database_records.html", {
        "title": resource.label, "resource": resource, "page": page, "rows": rows,
        "columns": [field_label(resource, field) for field in resource.columns],
        "query": query, "pagination_query": parameters.urlencode(),
        "related_field": request.GET.get("related_field", ""),
        "related_value": request.GET.get("related_value", ""),
        "related_label": field_label(resource, request.GET["related_field"]) if request.GET.get("related_field") else "",
        "clear_search_url": table_url(resource) + ("?" + search_parameters.urlencode() if search_parameters else ""),
        "clear_relation_url": table_url(resource) + ("?" + relation_parameters.urlencode() if relation_parameters else ""),
        "record_actions": editor_actions(resource, request),
    })


def database_record(request, table, pk):
    denied = _authorize(request)
    if denied:
        return denied
    resource = resource_for(table)
    if resource is None or not resource.detail:
        raise Http404
    try:
        queryset, _query = query_records(resource, {})
        obj = queryset.get(pk=pk)
        fields = [cell(resource, obj, field) for field in resource.fields]
        ordinary_fields, technical_fields = record_field_groups(resource, fields)
        actions = editor_actions(resource, request, obj)
        connected = dependencies(resource, obj)
        from qc_tool.frontend.dashboard.services.storage_admin.references import record_storage_links
        stored_files = record_storage_links(resource, obj)
    except (resource.model.DoesNotExist, ValidationError, ValueError, TypeError):
        raise Http404 from None
    except DatabaseError:
        return _render(request, "admin/database_records.html", {
            "title": resource.label, "resource": resource,
            "record_error": "This record could not be read. Check database availability and schema readiness before continuing.",
        }, status=503)
    return _render(request, "admin/database_record.html", {
        "title": f"{resource.label} · {pk}", "resource": resource, "record_pk": pk,
        "records_url": table_url(resource),
        "record_fields": fields, "record_actions": actions,
        "record_heading": record_heading(resource, obj),
        "ordinary_fields": ordinary_fields, "technical_fields": technical_fields,
        "record_dependencies": connected,
        "record_dependency_count": sum(item["count"] for item in connected),
        "record_storage_links": stored_files,
    })
