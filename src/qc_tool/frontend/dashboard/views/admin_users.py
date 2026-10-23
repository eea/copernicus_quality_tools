"""A permission-filtered entry point for existing account administration."""

from urllib.parse import urlencode

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.models import UserProductGrant


def _model_actions(request, model, *, list_label, add_label, description):
    registered = admin.site._registry.get(model)
    if registered is None or not registered.has_module_permission(request):
        return []
    prefix = f"admin:{model._meta.app_label}_{model._meta.model_name}_"
    actions = []
    if registered.has_add_permission(request):
        actions.append({"label": add_label, "url": reverse(prefix + "add"),
                        "description": "", "write": True})
    if registered.has_view_permission(request) or registered.has_change_permission(request):
        actions.append({"label": list_label, "url": reverse(prefix + "changelist"),
                        "description": description, "write": False})
    return actions


def user_management(request):
    """Navigate account tasks without creating, changing or deleting records."""
    access = access_for_request(request)
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied
    user_actions = _model_actions(
        request, get_user_model(), list_label="Manage users", add_label="Create user",
        description="Profiles, activation and account access",
    )
    group_actions = _model_actions(
        request, Group, list_label="Role groups", add_label="Create group",
        description="Group membership and permission bundles",
    )
    grant_actions = _model_actions(
        request, UserProductGrant, list_label="Product access", add_label="Assign product access",
        description="Assign products or QC definitions to users",
    )
    # The table browser is global and administrator-only; ordinary staff keep
    # their existing scoped ModelAdmin actions rather than unusable global links.
    if access.is_administrator:
        permission_action = {
            "label": "Permissions", "url": reverse("admin_database_records", args=["auth_permission"]),
            "description": "Inspect permission definitions; assign them through users or groups", "write": False,
        }
    else:
        permission_action = None
    if not access.is_administrator and not (user_actions or group_actions or grant_actions):
        raise PermissionDenied
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    transfers_url = reverse("admin_data_transfer")
    access_actions = [*group_actions, *grant_actions]
    if permission_action:
        access_actions.append(permission_action)
    context = {
        **admin.site.each_context(request),
        "title": "User management", "is_nav_sidebar_enabled": False,
        "user_actions": user_actions, "access_actions": access_actions,
        "can_transfer_users": access.is_administrator,
        "show_users_panel": bool(user_actions or access.is_administrator),
        "single_panel": not ((user_actions or access.is_administrator) and access_actions),
        "users_import_url": transfers_url + "?" + urlencode({"section": "users", "tab": "import"}),
        "users_export_url": transfers_url + "?" + urlencode({"section": "users", "tab": "export"}),
    }
    response = render(request, "admin/user_management.html", context)
    response["Cache-Control"] = "no-store, private"
    return response
