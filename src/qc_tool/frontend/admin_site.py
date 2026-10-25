"""Permission-aware task discovery and shared administration context."""

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.urls import get_script_prefix, reverse, reverse_lazy


def is_admin_request(request):
    """Recognize the Admin URL scope under a deployment script prefix."""
    admin_path = reverse("admin:index")
    prefix = get_script_prefix()
    if admin_path.startswith(prefix):
        admin_path = "/" + admin_path[len(prefix):]
    return request.path_info.startswith(admin_path)


class QCAdminSite(AdminSite):
    site_header = "QC Tool Admin"
    site_title = "QC Tool Admin"
    site_url = None
    enable_nav_sidebar = False
    index_template = "admin/qc_tool_index.html"

    def admin_view(self, view, cacheable=False):
        wrapped = super().admin_view(view, cacheable=cacheable)
        # Custom Admin routes need the same login destination as Django's
        # built-in routes when global LoginRequiredMiddleware runs first.
        wrapped.login_url = reverse_lazy("admin:login", current_app=self.name)
        return wrapped

    def get_app_list(self, request, app_label=None):
        # Model pages retain Django's permission-aware breadcrumbs. The custom
        # overview and database directory own task discovery and table policies.
        return super().get_app_list(request, app_label)

    def each_context(self, request):
        context = super().each_context(request)
        # Reuse Django's resolved model permissions, including permissions for
        # staff who may administer accounts without the QC administrator role.
        model_permissions = {
            (app["app_label"], model["object_name"]): model["perms"]
            for app in context["available_apps"] for model in app["models"]
        }
        user = get_user_model()
        context["admin_user_permissions"] = model_permissions.get(
            (user._meta.app_label, user._meta.object_name), {},
        )
        context["admin_group_permissions"] = model_permissions.get(("auth", "Group"), {})
        route = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
        section = "overview"
        if route.startswith("admin_database"):
            section = "database"
        if route.startswith(("admin_data_transfer", "admin_maintenance", "admin_backup_")):
            section = "maintenance"
        if route == "admin_user_management":
            section = "users"
        if route.startswith("admin_storage"):
            section = "storage"
        if route in {
            "boundaries", "boundaries_upload", "boundaries_upload_data",
            "boundaries_json", "boundaries_export", "boundaries_retention",
            "boundaries_retention_action",
        }:
            section = "boundaries"
        if route in {"admin_notifications", "announcement_update"}:
            section = "notifications"
        context["admin_user_management_available"] = any(
            any(perms.values()) for (label, name), perms in model_permissions.items()
            if (label, name) in {("auth", "User"), ("auth", "Group"),
                                 ("accounts", "UserProductGrant"), ("accounts", "PersonalAccessToken")}
        )
        if route == "index":
            from qc_tool.frontend.accounts.authorization import access_for_request
            from qc_tool.frontend.dashboard.services.admin_navigation import overview_directions
            context["admin_directions"] = overview_directions(
                request, can_manage_users=context["admin_user_management_available"],
                can_manage_access=(any(context["admin_group_permissions"].values())
                                   or access_for_request(request).is_administrator),
            )
        for model in self._registry:
            prefix = f"{model._meta.app_label}_{model._meta.model_name}_"
            if route.startswith(prefix):
                from qc_tool.frontend.dashboard.services.database_admin.resources import resource_for
                from qc_tool.frontend.dashboard.services.database_admin.presentation import table_url
                resource = resource_for(model._meta.db_table)
                if resource:
                    context["database_table_url"] = table_url(resource)
                    context["database_table_label"] = resource.label
                    section = "users" if model._meta.app_label in {"auth", "accounts"} else "database"
                    context["database_table_home_url"] = reverse("admin_user_management" if section == "users" else "admin_database")
                    context["database_table_home_label"] = "User management" if section == "users" else "Database"
                break
        table = getattr(getattr(request, "resolver_match", None), "kwargs", {}).get("table")
        if table:
            from qc_tool.frontend.dashboard.services.database_admin.resources import resource_for
            resource = resource_for(table)
            if resource and (resource.category == "Accounts & access" or table == "auth_permission"):
                section = "users"
        context["admin_section"] = section
        context["admin_database_active"] = section == "database"
        return context
