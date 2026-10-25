"""Permission-aware directions for the Admin overview.

Keep task discovery here; each destination enforces its own authorization.
"""

from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.database_navigation import database_tables_url


def overview_directions(request, *, can_manage_users, can_manage_access):
    directions = []
    if can_manage_users:
        users = reverse("admin_user_management")
        directions.append({
            "key": "users", "label": "User management", "icon": "users",
            "description": "Add, update or deactivate accounts and manage roles, permissions and product scope.",
            "url": users, "action_label": "Open user management",
            "tasks": ([{"label": "Roles and permissions", "url": users + "#user-access-heading",
                        "description": "Manage permitted groups and product scope", "icon": "shield"}]
                      if can_manage_access else []),
        })
    if not access_for_request(request).is_administrator:
        return directions
    directions.extend([
        {
            "key": "boundaries", "label": "Boundaries", "icon": "map-pin", "tone": "green",
            "description": "Preview raster and vector boundaries, replace the active package and manage retained versions.",
            "url": reverse("boundaries"), "action_label": "Manage boundaries",
            "tasks": [{"label": "Upload boundary package", "url": reverse("boundaries_upload"),
                       "description": "Validate a new package before activation", "icon": "upload"},
                      {"label": "Retained versions", "url": reverse("boundaries_retention"),
                       "description": "Review eligible packages for removal or recovery", "icon": "history"}],
        },
        {
            "key": "notifications", "label": "Notifications", "icon": "bell",
            "description": "Publish, update or remove the announcement shown in the QC workspace.",
            "url": reverse("admin_notifications"), "action_label": "Manage notifications", "tasks": [],
        },
        {
            "key": "database", "label": "Database", "icon": "columns", "tone": "violet",
            "description": "Inspect the active database name, version, tables, records and schema readiness.",
            "url": reverse("admin_database"), "action_label": "Inspect database",
            "tasks": [{"label": "Records by table", "url": database_tables_url(),
                       "description": "Browse records and their relationships", "icon": "folder"}],
        },
        {
            "key": "storage", "label": "Storage", "icon": "folder",
            "description": "Browse server files and folders, download retained data and review SFTP connection details.",
            "url": reverse("admin_storage"), "action_label": "Browse storage",
            "tasks": [{"label": "Connect with SFTP", "url": reverse("admin_storage") + "?tab=connection",
                       "description": "Connection details and operator setup guide", "icon": "settings"}],
        },
        {
            "key": "maintenance", "label": "Maintenance", "icon": "settings", "tone": "violet",
            "description": "Turn maintenance on or off, manage backups and restore a reviewed backup.",
            "url": reverse("admin_maintenance"), "action_label": "Open maintenance",
            "tasks": [],
        },
    ])
    return directions
