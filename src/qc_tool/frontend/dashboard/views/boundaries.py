"""Boundary catalog and package-management endpoints."""

import shutil
import tempfile

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.access.routes.csrf import boundary_upload_receive_failure
from qc_tool.frontend.dashboard.services.boundaries import BoundaryPackageError
from qc_tool.frontend.dashboard.services.boundaries import list_boundary_files
from qc_tool.frontend.dashboard.services.boundaries import replace_boundary_package
from qc_tool.frontend.dashboard.services.boundaries import resolve_boundary_generation
from qc_tool.frontend.dashboard.services.boundaries import inspect_boundary_capacity
from qc_tool.frontend.dashboard.services.boundaries.configuration import get_boundary_package_limits


_UPLOAD_FREE_HEADROOM = 256 * 1024**2


def boundaries(request):
    """
    Returns a list of all boundary aoi files in the active boundary package in html format.
    """
    return render(request, 'dashboard/boundaries/index.html', {})


def get_boundaries_json(request, boundary_type):
    """
    Returns a list of all boundary aoi files in the active boundary package in json format.

    :param request:
    :return: list of boundary .tif or .shp file infos with name and size in JSON format
    """
    if boundary_type not in {"raster", "vector"}:
        return JsonResponse(
            {
                "status": "error",
                "code": "invalid_boundary_type",
                "message": "Boundary type must be raster or vector.",
            },
            status=400,
        )

    try:
        generation = resolve_boundary_generation(CONFIG["boundary_dir"])
        directory = (
            generation.raster_dir
            if boundary_type == "raster"
            else generation.vector_dir
        )
        boundary_list = list_boundary_files(
            directory, boundary_type, max_entries=get_boundary_package_limits().max_members,
        )
    except BoundaryPackageError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.user_message,
            },
            status=exc.status_code,
        )

    return JsonResponse(
        [boundary_file.as_dict() for boundary_file in boundary_list],
        safe=False,
    )


def boundaries_upload_page(request):
    """Render the private boundary-upload page."""

    context = {}
    try:
        limits = get_boundary_package_limits()
        capacity = inspect_boundary_capacity(CONFIG["boundary_dir"])
        temporary_free = shutil.disk_usage(settings.FILE_UPLOAD_TEMP_DIR or tempfile.gettempdir()).free
        context.update(
            boundary_upload_limits=limits,
            boundary_storage_free=capacity["free_bytes"],
            boundary_available_upload_bytes=max(
                0, min(temporary_free, capacity["free_bytes"]) - _UPLOAD_FREE_HEADROOM,
            ),
        )
    except BoundaryPackageError as error:
        context["boundary_configuration_error"] = error.user_message
    except OSError:
        context["boundary_configuration_error"] = "Temporary upload storage is unavailable. Check server storage before uploading."
    return render(request, 'dashboard/boundaries/upload.html', context)


def boundaries_upload(request):
    """Validate and atomically activate a private boundary package upload."""

    try:
        limits = get_boundary_package_limits()
        uploaded_file = request.FILES.get("file")
    except BoundaryPackageError as error:
        return JsonResponse({"is_valid": False, "code": error.code, "message": error.user_message}, status=error.status_code)
    except OSError as error:
        return boundary_upload_receive_failure(error)
    if uploaded_file is None:
        return JsonResponse(
            {
                "is_valid": False,
                "code": "missing_boundary_package",
                "message": "A boundary package ZIP file is required.",
            },
            status=400,
        )

    try:
        result = replace_boundary_package(
            uploaded_file,
            CONFIG["boundary_dir"],
            limits=limits,
            lock_timeout=30,
        )
    except BoundaryPackageError as exc:
        return JsonResponse(
            {
                "is_valid": False,
                "code": exc.code,
                "message": exc.user_message,
            },
            status=exc.status_code,
        )

    return JsonResponse(
        {
            "is_valid": True,
            "message": "The boundary package was activated successfully.",
            "package": {
                "sha256": result.sha256,
                "archive_size": result.archive_size,
                "file_count": result.file_count,
                "uncompressed_size": result.uncompressed_size,
                "generation_id": result.generation_id,
            },
        }
    )
