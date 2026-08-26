"""Compatibility facade for API QC job endpoints.

Endpoint behavior lives in feature-specific modules.  Dependencies are passed
from this facade deliberately so existing integrations and tests can continue
to patch ``views.api_access.jobs.<dependency>``.
"""

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse
from django.http import JsonResponse

import qc_tool.frontend.dashboard.models as models
from qc_tool.common import check_running_job
from qc_tool.common import compile_job_report_data
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.dashboard.access import can_view_delivery
from qc_tool.frontend.dashboard.access import can_view_job
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_job_report
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import parse_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.jobs import serialize_job_report
from qc_tool.frontend.dashboard.views.api_access.jobs.creation import create_job
from qc_tool.frontend.dashboard.views.api_access.jobs.history import job_history
from qc_tool.frontend.dashboard.views.api_access.jobs.results import job_result
from qc_tool.frontend.dashboard.views.api_access.jobs.results import job_result_pdf
from qc_tool.frontend.dashboard.views.api_access.shared import (
    API_JSON_MAX_BODY_BYTES,
    _api_object_permission_denied,
    _json_request_error_response,
)
from qc_tool.jobs import normalize_job_uuid


def api_create_job(request):
    return create_job(
        request,
        maximum_body_bytes=API_JSON_MAX_BODY_BYTES,
        read_json=read_json_object,
        json_request_error_type=JsonRequestError,
        json_request_error_response=_json_request_error_response,
        parse_creation_request=parse_job_creation_request,
        job_request_error_type=JobRequestError,
        model_module=models,
        normalize_uuid=normalize_job_uuid,
    )


def api_job_result(request, job_uuid):
    return job_result(
        request,
        job_uuid,
        model_module=models,
        object_does_not_exist=ObjectDoesNotExist,
        can_view=can_view_job,
        permission_denied=_api_object_permission_denied,
        compile_report=compile_job_report_data,
        serialize_report=serialize_job_report,
    )


def api_job_result_pdf(request, job_uuid):
    return job_result_pdf(
        request,
        job_uuid,
        model_module=models,
        object_does_not_exist=ObjectDoesNotExist,
        can_view=can_view_job,
        permission_denied=_api_object_permission_denied,
        open_report=open_job_report,
        artifact_unavailable=ArtifactUnavailable,
        file_response=FileResponse,
    )


def api_job_history(request, delivery_id):
    return job_history(
        request,
        delivery_id,
        model_module=models,
        object_does_not_exist=ObjectDoesNotExist,
        can_view_delivery=can_view_delivery,
        can_view_job=can_view_job,
        permission_denied=_api_object_permission_denied,
        running_status=JOB_RUNNING,
        refresh_running_job=check_running_job,
        configuration=CONFIG,
        serialize_history=serialize_job_history,
    )


__all__ = (
    "api_create_job",
    "api_job_history",
    "api_job_result",
    "api_job_result_pdf",
)
