"""Browser mutation endpoints for persisted QC jobs."""

from django.http import JsonResponse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.jobs import JobDeletionError
from qc_tool.frontend.dashboard.services.jobs import delete_jobs_and_reproject
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import (
    parse_uuid_identifier_list,
)


def job_delete(request):
    """Delete eligible jobs and reproject their delivery metadata."""

    try:
        job_uuids = parse_uuid_identifier_list(request.POST.get("uuids"))
    except IdentifierListError as exc:
        return _error_response(exc.code, exc.message, status=400)

    try:
        deleted_count = delete_jobs_and_reproject(
            job_uuids,
            access_for_request(request),
        )
    except JobDeletionError as exc:
        return _error_response(
            exc.code,
            exc.message,
            status=exc.status_code,
        )
    return JsonResponse(
        {
            "status": "ok",
            "message": "{:d} jobs deleted successfully.".format(
                deleted_count
            ),
        }
    )


def _error_response(code, message, *, status):
    return JsonResponse(
        {"status": "error", "code": code, "message": message},
        status=status,
    )
