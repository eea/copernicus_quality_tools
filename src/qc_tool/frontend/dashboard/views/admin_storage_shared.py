"""Shared request authorization and page rendering for Admin storage views."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.admin_overview import overview_context
from qc_tool.frontend.dashboard.services.storage_admin import files
from qc_tool.frontend.dashboard.services.storage_admin.navigation import LIBRARIES, browse_url, tasks, url, locations as navigation_locations


def authorize(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied


def return_options(request):
    library = request.GET.get("library", "")
    if request.GET.get("browser") == "files" or library not in LIBRARIES:
        if not request.GET.get("area") and request.GET.get("browser") != "files":
            return {}
        values = {"browser": "files"}
        if request.GET.get("browse_query"):
            values["browse_query"] = request.GET["browse_query"][:150]
        if request.GET.get("browse_sort") in {"name", "modified", "size"}:
            values["browse_sort"] = request.GET["browse_sort"]
        if request.GET.get("browse_direction") in {"asc", "desc"}:
            values["browse_direction"] = request.GET["browse_direction"]
        try:
            page = int(request.GET.get("browse_page", "1"))
            if 1 < page <= 1_000_000:
                values["browse_page"] = page
        except (ValueError, TypeError):
            pass
        return values
    values = {"library": library}
    if library == "specifications" and request.GET.get("library_sources") == "1":
        values["library_sources"] = "1"
    if request.GET.get("library_query"):
        values["library_query"] = request.GET["library_query"][:150]
    status = request.GET.get("library_status", "")
    if status in {"all", "current", "previous", "archived", "unknown", "unavailable", "approved", "pending",
                  "conflict", "rejected", "publishing", "failed", "historical"}:
        values["library_status"] = status
    try:
        page = int(request.GET.get("library_page", "1"))
        if 1 < page <= 1_000_000:
            values["library_page"] = page
    except (ValueError, TypeError):
        pass
    return values


def library_url(options):
    return url(tab=options["library"], **{key: options[source] for key, source in
               (("q", "library_query"), ("status", "library_status"), ("page", "library_page"),
                ("include_sources", "library_sources"))
               if source in options}) if options.get("library") in LIBRARIES else ""


def folder_url(area, path, options):
    """Return to the exact physical folder view from file information."""
    return browse_url(area=area, path=path, **{key: options[source] for key, source in
                      (("q", "browse_query"), ("sort", "browse_sort"),
                       ("direction", "browse_direction"), ("page", "browse_page")) if source in options})


def folder_order(request):
    """Folder navigation keeps ordering and clears the previous folder's search."""
    return {key: request.GET[key] for key, allowed in
            (("sort", {"name", "modified", "size"}), ("direction", {"asc", "desc"}))
            if request.GET.get(key) in allowed}


def _library_folder(area, parts, options):
    """Name known library roots without exposing their implementation folders."""
    library = options.get("library")
    if library == "boundaries" and area == "boundaries" and len(parts) >= 2 and parts[0] == ".boundary-generations":
        return 2, "Boundary package files", "Boundary versions"
    if (library == "deliveries" and area == "published" and len(parts) >= 3
            and parts[2].startswith("submission-") and parts[2].endswith(".d")):
        return 3, "Submitted delivery files", "Submitted deliveries"
    if library == "specifications" and area == "uploaded-specifications" and len(parts) >= 3 and parts[0] == ".versions":
        return 3, "Specification file", "Product specifications"
    return None


def folder_title(area, path, options):
    parts = path.split("/") if path else []
    root = _library_folder(area, parts, options)
    return (root[1] if root and len(parts) == root[0] else parts[-1] if parts else
            files.area_info(area)["label"] if options.get("library") else
            files.location_label(area))


def breadcrumbs(area, path, options):
    result = [{"label": "All locations", "url": browse_url()}]
    if not area:
        return result
    info = files.area_info(area)
    files._parts(area, path)
    parts = path.split("/") if path else []
    root = _library_folder(area, parts, options)
    if root:
        depth, label, library_label = root
        result = [{"label": library_label, "url": library_url(options)},
                  {"label": label, "url": browse_url(area=area, path="/".join(parts[:depth]), **options)}]
        for index in range(depth, len(parts)):
            result.append({"label": parts[index], "url": browse_url(area=area, path="/".join(parts[:index + 1]), **options)})
        return result
    if not options.get("library"):
        order = {key: options[source] for key, source in
                 (("sort", "browse_sort"), ("direction", "browse_direction")) if source in options}
        result.append({"label": files.location_label(area),
                       "url": browse_url(area=area, **order)})
        for index, part in enumerate(parts):
            result.append({"label": part, "url": browse_url(area=area, path="/".join(parts[:index + 1]), **order)})
        return result
    result.append({"label": info["label"], "url": browse_url(area=area, **options)})
    for index, part in enumerate(parts):
        result.append({"label": part, "url": browse_url(area=area, path="/".join(parts[:index + 1]), **options)})
    return result


def render_storage(request, template, **context):
    status = context.pop("http_status", 200)
    area, path = context.get("area", ""), context.get("path", "")
    return_context = return_options(request)
    library = return_context.get("library", "")
    active = context.get("storage_tab") or library or "files"
    task_links = tasks(active)
    try:
        locations = navigation_locations(files.storage_locations())
        info = files.area_info(area) if area else {}
        crumb_context = return_context if library else {
            "browser": "files", **{"browse_" + key: value for key, value in folder_order(request).items()},
            **return_context}
        crumbs = breadcrumbs(area, path, crumb_context)
        storage_path = files.storage_path(area, path) if area else ""
    except files.StorageError:
        locations, info, crumbs, storage_path = [], {}, [{"label": "All locations", "url": browse_url()}], ""
    parts = path.split("/") if path else []
    library_root = _library_folder(area, parts, return_context)
    parent_url = (library_url(return_context) if library_root and len(parts) == library_root[0] else
                  browse_url(area=area, path=path.rpartition("/")[0], **return_context) if path else browse_url())
    if not library:
        parent_url = (browse_url(area=area, path=path.rpartition("/")[0], **folder_order(request))
                      if path else browse_url())
    response_context = {
        "storage_locations": [row for row in locations if row["group"] == "storage"],
        "storage_main_locations": [row for row in locations if row["group"] == "storage"],
        "storage_installation_locations": [row for row in locations if row["group"] == "installation"],
        "storage_is_installation": info.get("group") == "installation",
        "storage_tasks": task_links, "storage_tab": active,
        "storage_show_locations": active == "files",
        "storage_library": library,
        "storage_return_context": return_context,
        "physical_browse": not library and active == "files", "storage_path": storage_path,
        "location_path": path,
        "library_back_url": library_url(return_context),
        "library_back_label": next((task["label"] for task in task_links if task["key"] == library), ""),
        "area_info": info, "area_label": (files.location_label(area) if area and not library and info
                                           else info.get("label", "Storage")),
        "crumbs": crumbs, "connection_url": url(tab="connection"), "files_url": browse_url(),
        "backups_url": url("admin_data_transfer", tab="backups"),
        "parent_url": parent_url,
    }
    response = render(request, template, {
        **admin.site.each_context(request), "is_nav_sidebar_enabled": False,
        "admin_section": "storage", "title": "Storage", "storage_url": url(),
        "storage_overview": overview_context(request),
        "storage_generation": (getattr(request, "maintenance_status", {}) or {}).get("generation"),
        **response_context, **context,
    }, status=status)
    response["Cache-Control"] = "no-store, private"
    return response
