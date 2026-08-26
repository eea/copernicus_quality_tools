"""Authorized QC report, log, and attachment downloads."""

from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from qc_tool.common import compose_job_log_filepath
from qc_tool.common import compose_job_stdout_filepath
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.access import require_job_view
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_job_attachment
from qc_tool.frontend.dashboard.services.artifacts import open_job_report
from qc_tool.frontend.dashboard.services.artifacts import read_text_artifact


def get_pdf_report(request, job_uuid):
    """Download the generated PDF report for an authorized job."""

    _require_authorized_job(request, job_uuid)
    try:
        report_file, report_filename = open_job_report(job_uuid)
    except ArtifactUnavailable:
        raise Http404()
    return FileResponse(
        report_file,
        content_type="application/pdf",
        as_attachment=True,
        filename=report_filename,
    )


def get_combined_job_log(request, job_uuid):
    """Return stdout and detailed job logs as one text response."""

    _require_authorized_job(request, job_uuid)
    stdout_filepath = compose_job_stdout_filepath(job_uuid)
    joblog_filepath = compose_job_log_filepath(job_uuid)
    stdout_text = _read_log_or_default(
        stdout_filepath,
        "stdout log: no data.",
    )
    joblog_text = _read_log_or_default(
        joblog_filepath,
        "job log: no data.",
    )
    combined_log = (
        "STDOUT LOG:\n"
        + stdout_text
        + "DETAILED JOB LOG:\n"
        + joblog_text
    )
    return HttpResponse(combined_log, content_type="text/plain")


def get_attachment(request, job_uuid, attachment_filename):
    """Download one regular attachment belonging to an authorized job."""

    _require_authorized_job(request, job_uuid)
    try:
        attachment_file = open_job_attachment(job_uuid, attachment_filename)
    except ArtifactUnavailable:
        raise Http404()
    return FileResponse(
        attachment_file,
        as_attachment=True,
        filename=attachment_filename,
    )


def _require_authorized_job(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    return job


def _read_log_or_default(filepath, default):
    try:
        return read_text_artifact(filepath.parent, filepath.name)
    except ArtifactUnavailable:
        return default
