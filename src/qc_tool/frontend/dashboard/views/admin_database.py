"""Administrator record inspection. Writes use ordinary, guarded ModelAdmins."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import reverse
from django.utils.dateparse import parse_datetime

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.admin_overview import overview_context
from qc_tool.frontend.dashboard.services.database_admin.presentation import (
    cell, dependencies, editor_actions, field_label, query_records, record_rows, table_url,
)
from qc_tool.frontend.dashboard.services.database_admin.resources import resource_for, resources


def _authorize(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])


def _render(request, template, context, *, status=200):
    resource = context.get("resource")
    account_records = resource and (resource.category == "Accounts & access" or resource.table == "auth_permission")
    response = render(request, template, {
        **admin.site.each_context(request), "is_nav_sidebar_enabled": False,
        "database_url": reverse("admin_data_transfer"),
        "transfers_url": reverse("admin_data_transfer") + "?tab=transfers",
        "records_home_url": (reverse("admin_user_management") if account_records else
                             reverse("admin_data_transfer") + "?tables=1#database-records-heading"),
        "records_home_label": "User management" if account_records else "Database",
        **context,
    }, status=status)
    response["Cache-Control"] = "no-store, private"
    return response


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
    state = getattr(request, "maintenance_status", {}) or {}
    overview = overview_context(request)
    from qc_tool.database.policy import DatabasePolicyError, load_policy
    from qc_tool.database.transfers.service import schema_readiness
    try:
        policy = load_policy()
        policy_error = ""
    except DatabasePolicyError as error:
        policy, policy_error = {}, str(error)
    schema_status = schema_readiness()
    checked_at = schema_status.get("checked_at")
    return _render(request, "admin/database.html", {
        "title": "Database", "table_groups": groups.items(), "table_count": len(inventory),
        "categories": sorted({item.category for item in inventory}), "category": category, "query": query,
        "database_maintenance": state, "database_overview": overview,
        "maintenance_off": overview.get("phase") == "off",
        "maintenance_ready": overview.get("phase") == "ready" and not overview.get("transfer_url"),
        "database_policy": policy, "database_policy_error": policy_error,
        "database_schema_status": schema_status,
        "database_schema_checked_at": parse_datetime(checked_at) if isinstance(checked_at, str) else None,
        "tables_open": bool(query or category or request.GET.get("tables") == "1"),
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
    return _render(request, "admin/database_records.html", {
        "title": resource.label, "resource": resource, "page": page, "rows": rows,
        "columns": [field_label(resource, field) for field in resource.columns],
        "query": query, "pagination_query": parameters.urlencode(),
        "related_field": request.GET.get("related_field", ""),
        "related_value": request.GET.get("related_value", ""),
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
        "record_dependencies": connected,
        "record_storage_links": stored_files,
    })
