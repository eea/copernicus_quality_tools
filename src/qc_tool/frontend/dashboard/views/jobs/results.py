"""Rendered and JSON QC result endpoints."""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from qc_tool.common import compile_job_report_data
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.access import require_job_view
from qc_tool.frontend.dashboard.services.configuration.presentation import (
    get_announcement_message,
)
from qc_tool.frontend.dashboard.services.jobs import serialize_job_report


def get_result(request, job_uuid):
    """Render detailed results for an authorized QC job."""

    job = _get_authorized_job(request, job_uuid)
    job_report = _serialized_report(job, job_uuid)
    if job_report.get("status") is None:
        job_report["status"] = job.job_status
    _normalize_report_steps(job_report)
    return render(
        request,
        "dashboard/jobs/result.html",
        {
            "job_report": job_report,
            "delivery": job.delivery,
            "show_logo": settings.SHOW_LOGO,
            "announcement": get_announcement_message(),
        },
    )


def get_job_report(request, job_uuid):
    """Return the serialized JSON report for an authorized QC job."""

    job = _get_authorized_job(request, job_uuid)
    return JsonResponse(_serialized_report(job, job_uuid), safe=False)


def _get_authorized_job(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    return job


def _serialized_report(job, job_uuid):
    return serialize_job_report(
        compile_job_report_data(job_uuid, job.product_ident),
        job,
    )


def _normalize_report_steps(job_report):
    for step in job_report["steps"]:
        check_ident = step["check_ident"]
        if check_ident.startswith("qc_tool."):
            step["check_ident"] = ".".join(check_ident.split(".")[1:])
        if step["status"] == "aborted":
            job_report["aborted_check"] = step["check_ident"]
