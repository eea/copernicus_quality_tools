"""Shared navigation for read-only Database and guarded Maintenance tasks."""

from urllib.parse import urlencode

from django.urls import reverse


DATABASE_SECTIONS = (("overview", "Overview"), ("tables", "Tables & records"))
MAINTENANCE_SECTIONS = (("maintenance", "Maintenance mode"), ("backups", "Back up & restore"),
                        ("databases", "Manage databases"), ("activity", "Progress & history"))
TRANSFER_ORIGINS = {"backups", "activity", "databases"}


def database_tables_url():
    """Open the table directory from the top, including its heading and tabs."""
    return reverse("admin_database") + "?" + urlencode({"tables": "1"})


def transfer_origin(request):
    origin = request.GET.get("from")
    return origin if origin in TRANSFER_ORIGINS else "backups"


def maintenance_task_urls():
    """Share backup destinations without requiring a task navigation bar."""
    transfer_url = reverse("admin_data_transfer")
    export_url = reverse("admin_backup_export")
    import_url = reverse("admin_backup_import")
    return {
        "database_manager_url": transfer_url + "?" + urlencode({"tab": "databases"}),
        "export_page_url": export_url,
        "import_page_url": import_url,
        "area_export_url": export_url,
        "area_import_url": import_url,
        "backup_files_url": export_url + "#prepared-backups",
        "transfer_history_url": export_url + "#backup-history",
    }


def transfer_workspace_context(workflow, title, description, operation=False):
    """Compose one transfer journey using only server-owned Admin routes."""
    if workflow not in {"export", "import"}:
        raise ValueError("Choose an export or import workspace.")
    urls = maintenance_task_urls()
    page_url = urls[f"{workflow}_page_url"]
    page_label = "Create backup" if workflow == "export" else "Restore from ZIP"
    maintenance_url = reverse("admin_maintenance")
    crumbs = [
        {"label": "Maintenance", "url": maintenance_url},
        {"label": page_label, "url": page_url if operation else ""},
    ]
    if operation:
        crumbs.append({"label": title, "url": ""})
    return {
        **urls,
        "title": title,
        "database_page_title": title,
        "database_page_description": description,
        "database_breadcrumbs": crumbs,
        "database_sections": [],
        "hide_database_navigation": True,
        "database_back_url": page_url if operation else maintenance_url,
        "database_back_label": "Back to " + (page_label if operation else "Maintenance"),
        "database_url": reverse("admin_database"),
        "transfer_history_url": page_url + ("#backup-history" if workflow == "export" else "#import-history"),
    }


def database_page_context(section, *, title, description, child=False, origin="backups", workspace="database"):
    """Build destinations from known Admin routes, never arbitrary return URLs."""
    database_url = reverse("admin_database")
    transfer_url = reverse("admin_data_transfer")
    urls = {
        "overview": database_url,
        "tables": database_tables_url(),
        "maintenance": reverse("admin_maintenance"),
        **{key: transfer_url + "?" + urlencode({"tab": key})
           for key in ("backups", "databases", "activity")},
    }
    is_maintenance = workspace == "maintenance"
    sections = MAINTENANCE_SECTIONS if is_maintenance else DATABASE_SECTIONS
    root = "maintenance" if is_maintenance else "overview"
    labels = dict(sections)
    parent = origin if child and origin in labels else root
    show_back = child or (is_maintenance and section != root)
    crumbs = [{"label": "Maintenance" if is_maintenance else "Database", "url": urls[root]}]
    if child and parent != root:
        crumbs.append({"label": labels[parent], "url": urls[parent]})
    if section != root or child:
        crumbs.append({"label": title, "url": ""})
    else:
        crumbs[0]["url"] = ""
    return {
        "title": title, "database_page_title": title, "database_page_description": description,
        "database_breadcrumbs": crumbs,
        "database_navigation_label": "Maintenance tasks" if is_maintenance else "Database sections",
        "database_sections": [{"key": key, "label": label,
                               "url": urls[key], "active": key == section}
                              for key, label in sections],
        "database_back_url": urls[parent] if show_back else "",
        "database_back_label": ("Back to " + ("Maintenance" if parent == "maintenance" else labels[parent])
                                if show_back else ""),
        "database_url": database_url,
        "database_tables_url": urls["tables"],
        **maintenance_task_urls(),
    }
