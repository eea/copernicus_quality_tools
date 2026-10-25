"""Read-only libraries over existing submission and reference version sources."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import datetime

from django.http import HttpResponseNotAllowed

from qc_tool.frontend.dashboard.services.storage_admin import files
from qc_tool.frontend.dashboard.services.storage_admin.navigation import url
from .admin_storage_shared import authorize, render_storage


_PAGES = {
    "deliveries": ("Submitted deliveries", "Find submitted deliveries, their approval status and retained files in one place."),
    "specifications": ("Product specifications", "Find original specification versions and see which versions are currently selected."),
    "boundaries": ("Boundary versions", "Find saved boundary packages and see which version is currently selected."),
}


def _with_library(address, return_context):
    if not address:
        return ""
    parts = urlsplit(address)
    # All links are built by our inventories; keep return context local and fixed.
    if parts.scheme or parts.netloc or not parts.path.startswith("/admin/storage/"):
        return address
    values = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.startswith("library")]
    return urlunsplit(("", "", parts.path, urlencode([*values, *return_context.items()]), parts.fragment))


def storage_library(request):
    authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    tab = request.GET.get("tab", "deliveries")
    if tab not in _PAGES:
        tab = "deliveries"
    query = request.GET.get("q", "")[:150]
    include_sources = tab == "specifications" and request.GET.get("include_sources") == "1"
    status = request.GET.get("status", "all" if tab == "deliveries" else "current")
    page = request.GET.get("page", "1")
    if tab == "deliveries":
        from qc_tool.frontend.dashboard.services.storage_admin.deliveries import inventory
        listing = inventory(query=query, status=status, page=page)
    else:
        from qc_tool.frontend.dashboard.services.storage_admin.versions import list_versions
        try:
            listing = list_versions(tab, query=query, status=status, page=page,
                                    include_sources=include_sources if tab == "specifications" else True)
        except files.StorageError as error:
            listing = {"entries": [], "available": False, "message": str(error), "total": 0,
                       "page": 1, "warnings": [], "status": "all"}
    return_context = {"library": tab, "library_status": listing.get("status", status)}
    if include_sources:
        return_context["library_sources"] = "1"
    if query:
        return_context["library_query"] = query
    if listing.get("page", 1) > 1:
        return_context["library_page"] = listing["page"]
    for entry in listing["entries"]:
        if tab == "deliveries":
            entry["files_url"] = _with_library(entry.get("files_url"), return_context)
            entry["download_url"] = _with_library(entry.get("download_url"), return_context)
        else:
            area, path = entry.get("area"), entry.get("path")
            entry["history_url"] = url(tab=tab, q=entry.get("product_ident") or "", status="all",
                                       **({"include_sources": "1"} if include_sources else {}))
            for field in ("modified_at", "imported_at"):
                if isinstance(entry.get(field), str):
                    entry[field] = datetime.fromisoformat(entry[field])
            if entry.get("available") and area and path is not None:
                entry["files_url"] = url("admin_storage" if entry["kind"] == "directory" else "admin_storage_file",
                                         area=area, path=path, **return_context)
                if entry["kind"] == "directory":
                    entry["download_url"] = url("admin_storage_archive", area=area, selection="1",
                                                paths=entry.get("selection_paths") or [path], folder=path, **return_context)
                else:
                    entry["download_url"] = url("admin_storage_download", area=area, path=path, **return_context)
    title, description = _PAGES[tab]
    status = listing.get("status", status)
    filtered = bool(query) or include_sources or status != ("all" if tab == "deliveries" else "current")
    options = {"tab": tab, "q": query, "status": status}
    if include_sources:
        options["include_sources"] = "1"
    current_page = listing.get("page", 1)
    filters = listing.get("filters") if tab == "deliveries" else [
        {"value": "all", "label": "All versions"}, {"value": "current", "label": "Current"},
        {"value": "previous", "label": "Previous"}, {"value": "archived", "label": "Archived"},
        {"value": "unavailable", "label": "Originals unavailable"},
        {"value": "unknown", "label": "Selection unknown"},
    ]
    filters = [{**item, "value": item.get("value", item.get("key", ""))} for item in filters]
    shortcut_keys = {"all", "approved", "pending", "historical"} if tab == "deliveries" else {"all", "current", "previous"}
    shortcuts = [{**item, "url": url(**{**options, "status": item["value"]}), "active": item["value"] == status}
                 for item in filters if item["value"] in shortcut_keys]
    return render_storage(request, "admin/storage_library.html", title=title, storage_tab=tab,
                          library_description=description, library_listing=listing, library_kind=tab,
                          library_filters=filters, library_shortcuts=shortcuts, library_filtered=filtered,
                          query=query, status=status, include_sources=include_sources,
                          clear_library_url=url(tab=tab),
                          refresh_library_url=url(**options, page=current_page),
                          library_previous_url=url(**options, page=max(current_page - 1, 1)),
                          library_next_url=url(**options, page=current_page + 1))
