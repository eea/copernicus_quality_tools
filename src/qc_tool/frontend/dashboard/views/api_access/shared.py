"""Shared response helpers for API access endpoints."""

from django.http import JsonResponse


API_JSON_MAX_BODY_BYTES = 16 * 1024


def _json_request_error_response(error):
    return JsonResponse(
        {
            "status": "error",
            "code": error.code,
            "message": error.message,
        },
        status=error.status_code,
    )


def _api_object_permission_denied(object_name):
    return JsonResponse(
        {
            "status": "error",
            "code": "object_permission_denied",
            "message": f"The account cannot access this {object_name}.",
        },
        status=403,
    )
