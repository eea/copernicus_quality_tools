"""Boundary catalog and package-management endpoints."""

from django.http import JsonResponse
from django.shortcuts import render
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.boundaries import BoundaryPackageError
from qc_tool.frontend.dashboard.services.boundaries import list_boundary_files
from qc_tool.frontend.dashboard.services.boundaries import replace_boundary_package
from qc_tool.frontend.dashboard.services.boundaries import resolve_boundary_generation


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
        boundary_list = list_boundary_files(directory, boundary_type)
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

    return render(request, 'dashboard/boundaries/upload.html')


def boundaries_upload(request):
    """Validate and atomically activate a private boundary package upload."""

    uploaded_file = request.FILES.get("file")
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
            },
        }
    )
