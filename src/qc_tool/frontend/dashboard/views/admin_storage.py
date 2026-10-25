"""Administrative filesystem browsing, independent of imported SQL records."""

import hashlib
import os
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, HttpResponseNotAllowed, StreamingHttpResponse
from django.shortcuts import redirect
from django.utils.http import content_disposition_header

from qc_tool.frontend.dashboard.services.admin_feedback import busy_context
from qc_tool.frontend.dashboard.services.storage_admin.navigation import url as _url, browse_url, library_key
from .admin_storage_shared import (authorize as _authorize, render_storage as _render, return_options,
                                   folder_title, library_url, folder_url, folder_order)


_TRASH_STATES = {
    "quarantined": "In trash", "moving": "Needs recovery", "restoring": "Needs recovery",
    "restored": "Restored", "recovery_required": "Needs recovery",
}


def _display_entry(entry):
    if entry.get("modified_at"):
        try:
            entry["modified_at"] = datetime.fromisoformat(entry["modified_at"])
        except (ValueError, TypeError):
            entry["modified_at"] = None
    return entry


def _modules():
    from qc_tool.frontend.dashboard.services.storage_admin import files, references, trash
    return files, references, trash


def storage_home(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, _references, _trash = _modules()
    tab = request.GET.get("tab", "")
    if not tab and not request.GET.get("area") and getattr(settings, "QC_TOOL_PERSISTENT_STORAGE_ROOT", ""):
        return redirect(browse_url(area="persistent"))
    if not request.GET.get("area") and library_key(tab, request.GET.get("collection", "")):
        from .admin_storage_library import storage_library
        return storage_library(request)
    if request.GET.get("tab") == "connection":
        from qc_tool.frontend.dashboard.services.storage_admin.connections import connection_info
        return _render(request, "admin/storage_connection.html", title="Connect to storage", storage_tab="connection",
                       connection=connection_info())
    area, path = request.GET.get("area", ""), request.GET.get("path", "")
    if not area:
        return _render(request, "admin/storage.html", title="Browse files", storage_tab="files")
    try:
        return_context = return_options(request)
        physical = not return_context.get("library")
        sort = request.GET.get("sort", "name")
        if sort not in {"name", "modified", "size"}:
            sort = "name"
        descending = request.GET.get("direction") == "desc"
        listing = files.list_entries(area, path, page=request.GET.get("page", "1"), query=request.GET.get("q", ""),
                                     sort=sort, descending=descending)
        detail_context = return_context
        if physical:
            detail_context = {"browser": "files", "browse_sort": sort,
                              "browse_direction": "desc" if descending else "asc"}
            if request.GET.get("q"):
                detail_context["browse_query"] = request.GET["q"][:150]
            if listing["page"] > 1:
                detail_context["browse_page"] = listing["page"]
        for row in listing["entries"]:
            _display_entry(row)
            row["url"] = (browse_url(area=area, path=row["path"], **folder_order(request))
                          if physical and row["kind"] == "directory" else
                          _url("admin_storage" if row["kind"] == "directory" else "admin_storage_file",
                               area=area, path=row["path"], **detail_context))
            row["download_url"] = _url("admin_storage_archive" if row["kind"] == "directory" else "admin_storage_download",
                                      area=area, path=row["path"], folder=path, **detail_context)
        navigation_context = {"tab": "files", "browser": "files"} if physical else return_context
        options = {"area": area, "path": path, "q": request.GET.get("q", "")[:150],
                   "sort": sort, "direction": "desc" if descending else "asc", **navigation_context}
        sort_urls = {"sort_" + key + "_url": _url(**{**options, "sort": key,
                      "direction": "asc" if sort == key and descending else "desc" if sort == key else "asc"})
                     for key in ("name", "modified", "size")}
        return _render(request, "admin/storage.html", listing=listing, area=area, path=path,
                       title=folder_title(area, path, return_context),
                       query=request.GET.get("q", ""), sort=sort, direction=options["direction"],
                       refresh_url=_url(**options, page=listing["page"]), clear_search_url=_url(area=area, path=path, sort=sort, direction=options["direction"], **navigation_context),
                       previous_url=_url(**options, page=int(listing["page"]) - 1),
                       next_url=_url(**options, page=int(listing["page"]) + 1),
                       archive_url=_url("admin_storage_archive", area=area, path=path, folder=path, **detail_context),
                       trash_url=_url("admin_storage_trash", area=area, path=path, **detail_context), **sort_urls)
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409), **busy_context(error),
                       admin_busy_refresh_url=_url(area=area))


def storage_file(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, references, trash = _modules()
    area, path = request.GET.get("area", ""), request.GET.get("path", "")
    try:
        return_context = return_options(request)
        entry = files.inspect_entry(area, path)
        info = files.area_info(area)
        try:
            review = (trash.preview_quarantine(area, path, actor=request.user) if info["can_trash"] else
                      {"can_quarantine": False, "message": "This location is available for browsing and downloading. Files are managed by their owning application workflow."})
        except files.StorageError as error:
            if getattr(error, "status_code", 409) not in {403, 503}:
                raise
            # Read access remains useful during database recovery. A different
            # active-database identity must still never authorize file changes.
            review = {"can_quarantine": False, "message": str(error)}
        # The visible metadata and confirmation must describe the same review.
        # A replacement during the initial inspection cannot inherit a different
        # file's review hash while still displaying the old size and timestamp.
        entry = review.get("entry", entry)
        usage = (review.get("usage") or references.describe_references(area, path) if info["can_trash"] else
                 {"status_label": "Browse and download", "message": "Original files remain unchanged when you browse or download them."})
        evidence = None
        if request.GET.get("verify") == "1":
            checksum, length = hashlib.sha256(), 0
            with files.open_file(area, path) as handle:
                if files.entry_fingerprint(os.fstat(handle.fileno())) != entry["fingerprint"]:
                    raise files.StorageError("The file changed while it was opened. Reopen and verify it again.")
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    checksum.update(block)
                    length += len(block)
                if files.entry_fingerprint(os.fstat(handle.fileno())) != entry["fingerprint"]:
                    raise files.StorageError("The file changed while it was checked. Reopen and verify it again.")
            if files.inspect_entry(area, path)["fingerprint"] != entry["fingerprint"]:
                raise files.StorageError("The file changed while it was checked. Reopen and verify it again.")
            evidence = {"sha256": checksum.hexdigest(), "size": length}
            if info["can_trash"]:
                usage = references.describe_references(area, path, evidence=evidence)
        return _render(request, "admin/storage_file.html", entry=_display_entry(entry), review=review, usage=usage,
                       evidence=evidence, area=area, path=path,
                       title=("Specification file" if return_context.get("library") == "specifications"
                              else entry["name"]),
                       zip_file=path.casefold().endswith(".zip"),
                       parent_url=(library_url(return_context) if return_context.get("library") == "specifications"
                                   else _url(area=area, path=path.rpartition("/")[0], **return_context)
                                   if return_context.get("library") else folder_url(area, path.rpartition("/")[0], return_context)),
                       download_url=_url("admin_storage_download", area=area, path=path, **return_context),
                       verify_url=_url("admin_storage_file", area=area, path=path, verify=1, **return_context))
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))
    except OSError:
        return _render(request, "admin/storage.html", storage_error="The file could not be read completely. Reopen it before continuing.",
                       area=area, http_status=503)


def storage_download(request):
    _authorize(request)
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])
    files, _references, _trash = _modules()
    area, path = request.GET.get("area", ""), request.GET.get("path", "")
    try:
        stream = files.open_file(area, path)
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))
    from qc_tool.database.transfers import downloads
    response = downloads.response(stream, {"filename": path.rsplit("/", 1)[-1]}, request)
    response["Content-Type"] = "application/octet-stream"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    return response


def storage_archive(request):
    """Confined, bounded inventory followed by a streaming ZIP download."""
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    from qc_tool.frontend.dashboard.services.storage_admin import downloads, files
    area, folder = request.GET.get("area", ""), request.GET.get("folder", "")
    paths = request.GET.getlist("paths") if request.GET.get("selection") == "1" else [request.GET.get("path", "")]
    try:
        if not paths or (request.GET.get("selection") == "1" and any(not path for path in paths)):
            raise files.StorageError("Select at least one file or folder to download.", status_code=400)
        plan = downloads.prepare_zip(area, paths)
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area, path=folder,
                       http_status=getattr(error, "status_code", 409))
    response = StreamingHttpResponse(downloads.stream_zip(plan), content_type="application/zip")
    response["Content-Disposition"] = content_disposition_header(True, plan.filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    response["X-QC-Storage-Excluded-Entries"] = str(plan.excluded_count)
    return response


def storage_connection_guide(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    guide = Path(__file__).resolve().parents[5] / "docs" / "deployment" / "storage-access.md"
    try:
        handle = guide.open("rb")
    except OSError:
        return _render(request, "admin/storage_connection.html", storage_tab="connection", title="Connect to storage",
                       storage_error="The setup guide is not available in this installation. See the deployment documentation for storage access.", http_status=503)
    response = FileResponse(handle, as_attachment=True, filename="qc-tool-storage-access.md", content_type="text/markdown; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def storage_trash(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, _references, trash = _modules()
    area = request.GET.get("area", "incoming")
    path = request.GET.get("path", "")
    return_context = return_options(request)
    try:
        if not files.area_info(area)["can_trash"]:
            raise files.StorageError("This location has no managed Trash.", status_code=404)
        files._parts(area, path)
        listing = trash.list_trash(area, page=request.GET.get("page", "1"))
        for entry in listing["entries"]:
            entry["state_label"] = _TRASH_STATES.get(entry["state"], "Needs review")
        options = {"area": area, "path": path, **return_context}
        back_url = (_url(area=area, path=path, **return_context) if return_context.get("library")
                    else folder_url(area, path, return_context))
        return _render(request, "admin/storage_trash.html", area=area, path=path, trash_listing=listing, title="Trash",
                       parent_url=back_url,
                       trash_previous_url=_url("admin_storage_trash", **options, page=max(1, listing["page"] - 1)),
                       trash_next_url=_url("admin_storage_trash", **options, page=listing["page"] + 1))
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))


def storage_action(request):
    _authorize(request)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    files, _references, trash = _modules()
    area, path = request.POST.get("area", ""), request.POST.get("path", "")
    return_context = return_options(request)
    try:
        if not files.area_info(area)["can_trash"]:
            raise files.StorageError("This location is available for browsing and downloading only.")
        try:
            generation = int(request.POST.get("generation", ""))
        except (ValueError, TypeError):
            raise files.StorageError("Maintenance changed. Reload and review this action.") from None
        if request.POST.get("action") == "quarantine":
            return_folder = path.rpartition("/")[0]
            entry = files.inspect_entry(area, path)
            if request.POST.get("confirmed") != "on" or request.POST.get("filename_confirmation") != entry["name"]:
                raise files.StorageError("Confirm the filename before moving this file to trash.")
            trash.quarantine(area, path, actor=request.user, generation=generation,
                             review_hash=request.POST.get("review_hash", ""))
        elif request.POST.get("action") == "restore":
            return_folder = request.POST.get("folder", "")
            files._parts(area, return_folder)
            trash.restore(area, request.POST.get("operation_id", ""), actor=request.user, generation=generation)
        else:
            raise files.StorageError("Choose a supported storage action.")
        return redirect(_url("admin_storage_trash", area=area, path=return_folder, **return_context))
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409), **busy_context(error),
                       admin_busy_refresh_url=_url("admin_storage_trash", area=area))
