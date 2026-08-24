"""Generic machine-readable errors shared by protected account endpoints."""

from django.http import JsonResponse


_NOT_FOUND_MESSAGE = "The requested resource was not found."


def json_not_found_response():
    """Return a generic 404 without exposing resource or lookup details."""

    return JsonResponse(
        {
            "status": "error",
            "code": "not_found",
            "message": _NOT_FOUND_MESSAGE,
        },
        status=404,
    )
