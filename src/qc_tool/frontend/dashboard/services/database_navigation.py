"""Shared presentation and safe return destinations for Database administration."""

from urllib.parse import urlencode

from django.urls import reverse


SECTIONS = (("overview", "Database status"), ("backups", "Back up & restore"),
            ("databases", "Manage databases"), ("activity", "Progress & history"))
SECTION_HINTS = {
    "overview": "Active database and readiness",
    "backups": "Create, download or restore ZIPs",
    "databases": "Inspect, switch or remove databases",
    "activity": "Running and past transfers",
}
TRANSFER_ORIGINS = {"backups", "activity", "databases"}


def transfer_origin(request):
    origin = request.GET.get("from")
    return origin if origin in TRANSFER_ORIGINS else "backups"


def database_page_context(section, *, title, description, child=False, origin="backups"):
    """Use only known local destinations, never arbitrary return URLs."""
    base = reverse("admin_data_transfer")
    urls = {key: base + ("?" + urlencode({"tab": key}) if key != "overview" else "")
            for key, _ in SECTIONS}
    parent = origin if child and origin in dict(SECTIONS) else "overview"
    parent_label = dict(SECTIONS)[parent]
    crumbs = [{"label": "Database status", "url": base}]
    if child and parent != "overview":
        crumbs.append({"label": dict(SECTIONS)[parent], "url": urls[parent]})
    if section != "overview" or child:
        crumbs.append({"label": title, "url": ""})
    else:
        crumbs[0]["url"] = ""
    return {
        "title": title, "database_page_title": title, "database_page_description": description,
        "database_breadcrumbs": crumbs,
        "database_sections": [{"key": key, "label": label, "hint": SECTION_HINTS[key],
                               "url": urls[key], "current": key == section}
                              for key, label in SECTIONS],
        "database_back_url": urls[parent] if section != "overview" or child else "",
        "database_back_label": "Back to " + parent_label,
        "database_url": base, "database_manager_url": urls["databases"],
        "backup_files_url": urls["backups"], "transfer_history_url": urls["activity"],
        "area_export_url": base + "?tab=export", "area_import_url": base + "?tab=import",
    }
