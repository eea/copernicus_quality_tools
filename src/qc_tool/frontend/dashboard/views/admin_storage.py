"""Administrative filesystem browsing, independent of imported SQL records."""

import hashlib
import os
from datetime import datetime
from urllib.parse import urlencode

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.admin_overview import overview_context


_AREA_PRESENTATION = {
    "incoming": ("Delivery uploads", "Original delivery ZIPs, grouped by uploader."),
    "jobs": ("QC job artifacts", "Retained job inputs, reports and logs, grouped by job identifier."),
    "published": ("Published submissions", "Immutable files retained as published submission evidence."),
}
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


def _authorize(request):
    if not access_for_request(request).is_administrator:
        raise PermissionDenied


def _modules():
    from qc_tool.frontend.dashboard.services.storage_admin import files, references, trash
    return files, references, trash


def _url(name="admin_storage", **values):
    return reverse(name) + ("?" + urlencode(values) if values else "")


def _breadcrumbs(area, path):
    result = [{"label": _AREA_PRESENTATION.get(area, (area, ""))[0], "url": _url(area=area)}]
    parts = path.split("/") if path else []
    for index, part in enumerate(parts):
        result.append({"label": part, "url": _url(area=area, path="/".join(parts[:index + 1]))})
    return result


def _render(request, template, **context):
    status = context.pop("http_status", 200)
    response = render(request, template, {
        **admin.site.each_context(request), "is_nav_sidebar_enabled": False,
        "admin_section": "storage", "title": "Storage", "storage_url": reverse("admin_storage"),
        "storage_overview": overview_context(request),
        "storage_generation": (getattr(request, "maintenance_status", {}) or {}).get("generation"),
        **context,
        "area_label": _AREA_PRESENTATION.get(context.get("area"), ("Storage", ""))[0],
    }, status=status)
    response["Cache-Control"] = "no-store, private"
    return response


def storage_home(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, _references, _trash = _modules()
    area, path = request.GET.get("area", ""), request.GET.get("path", "")
    if not area:
        areas = files.storage_areas()
        for item in areas:
            item["description"] = _AREA_PRESENTATION.get(item["key"], ("", ""))[1]
        return _render(request, "admin/storage.html", storage_areas=areas)
    try:
        listing = files.list_entries(area, path, page=request.GET.get("page", "1"), query=request.GET.get("q", ""))
        for row in listing["entries"]:
            _display_entry(row)
            row["url"] = _url("admin_storage" if row["kind"] == "directory" else "admin_storage_file",
                              area=area, path=row["path"])
        return _render(request, "admin/storage.html", listing=listing, area=area, path=path,
                       query=request.GET.get("q", ""), crumbs=_breadcrumbs(area, path),
                       previous_url=_url(area=area, path=path, q=request.GET.get("q", ""), page=int(listing["page"]) - 1),
                       next_url=_url(area=area, path=path, q=request.GET.get("q", ""), page=int(listing["page"]) + 1),
                       trash_url=_url("admin_storage_trash", area=area))
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))


def storage_file(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, references, trash = _modules()
    area, path = request.GET.get("area", ""), request.GET.get("path", "")
    try:
        entry = files.inspect_entry(area, path)
        try:
            review = trash.preview_quarantine(area, path, actor=request.user)
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
        usage = review.get("usage") or references.describe_references(area, path)
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
            usage = references.describe_references(area, path, evidence=evidence)
        return _render(request, "admin/storage_file.html", entry=_display_entry(entry), review=review, usage=usage,
                       evidence=evidence, area=area, path=path,
                       zip_file=path.casefold().endswith(".zip"),
                       parent_url=_url(area=area, path=path.rpartition("/")[0]),
                       download_url=_url("admin_storage_download", area=area, path=path),
                       verify_url=_url("admin_storage_file", area=area, path=path, verify=1))
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))
    except OSError:
        return _render(request, "admin/storage.html", storage_error="The file could not be read completely. Reopen it before continuing.",
                       area=area, http_status=503)


def storage_download(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, _references, _trash = _modules()
    area, path = request.GET.get("area", ""), request.GET.get("path", "")
    try:
        stream = files.open_file(area, path)
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))
    response = FileResponse(stream, as_attachment=True, filename=path.rsplit("/", 1)[-1],
                            content_type="application/octet-stream")
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    return response


def storage_trash(request):
    _authorize(request)
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    files, _references, trash = _modules()
    area = request.GET.get("area", "incoming")
    try:
        listing = trash.list_trash(area, page=request.GET.get("page", "1"))
        for entry in listing["entries"]:
            entry["state_label"] = _TRASH_STATES.get(entry["state"], "Needs review")
        return _render(request, "admin/storage_trash.html", area=area, trash_listing=listing)
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))


def storage_action(request):
    _authorize(request)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    files, _references, trash = _modules()
    area, path = request.POST.get("area", ""), request.POST.get("path", "")
    try:
        try:
            generation = int(request.POST.get("generation", ""))
        except (ValueError, TypeError):
            raise files.StorageError("Maintenance changed. Reload and review this action.") from None
        if request.POST.get("action") == "quarantine":
            entry = files.inspect_entry(area, path)
            if request.POST.get("confirmed") != "on" or request.POST.get("filename_confirmation") != entry["name"]:
                raise files.StorageError("Confirm the filename before moving this file to trash.")
            trash.quarantine(area, path, actor=request.user, generation=generation,
                             review_hash=request.POST.get("review_hash", ""))
        elif request.POST.get("action") == "restore":
            trash.restore(area, request.POST.get("operation_id", ""), actor=request.user, generation=generation)
        else:
            raise files.StorageError("Choose a supported storage action.")
        return redirect(_url("admin_storage_trash", area=area))
    except files.StorageError as error:
        return _render(request, "admin/storage.html", storage_error=str(error), area=area,
                       http_status=getattr(error, "status_code", 409))
