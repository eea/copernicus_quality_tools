"""API QC job lifecycle and result endpoints."""

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse
from django.http import JsonResponse
import qc_tool.frontend.dashboard.models as models
from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.common import compile_job_report_data
from qc_tool.jobs import normalize_job_uuid
from qc_tool.frontend.dashboard.access import can_view_job
from qc_tool.frontend.dashboard.access import can_view_delivery
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_job_report
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import parse_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.jobs import serialize_job_report

from qc_tool.frontend.dashboard.views.api_access.shared import (
    API_JSON_MAX_BODY_BYTES,
    _api_object_permission_denied,
    _json_request_error_response,
)


def api_create_job(request):
    try:
        body_json = read_json_object(
            request,
            maximum_bytes=API_JSON_MAX_BODY_BYTES,
        )
        job_request = parse_job_creation_request(body_json)
    except JsonRequestError as exc:
        return _json_request_error_response(exc)
    except JobRequestError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.message,
            },
            status=400,
        )

    # Update delivery status in the frontend database.
    try:
        d = models.Delivery.objects.get(id=job_request.delivery_id)
    except ObjectDoesNotExist:
        result = {
            "status": "error",
            "message": "delivery with id={} not found.".format(
                job_request.delivery_id
            ),
        }
        return JsonResponse(result, status=404)

    # Scoped managers may read other users' deliveries, but only an owner or
    # administrator may mutate one.
    if not request.api_access.can_manage_user(d.user_id):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot modify this delivery.",
            },
            status=403,
        )

    job_uuid = d.create_job(
        job_request.product_ident,
        job_request.skip_steps,
    )

    response_data = {"job_uuid": normalize_job_uuid(job_uuid)}
    result = {"status": "OK", "message": "QC job successfully created", "data": response_data}
    return JsonResponse(result)


def api_job_result(request, job_uuid):
    try:
        job = models.Job.objects.get(job_uuid=job_uuid)
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "job with uuid={} does not exist.".format(job_uuid)}
        return JsonResponse(result, status=404)

    if not can_view_job(request.api_access, job):
        return _api_object_permission_denied("job")

    job_report = serialize_job_report(
        compile_job_report_data(job_uuid, job.product_ident),
        job,
    )
    response_data = {"status": "ok", "message": "job status", "data": job_report}
    return JsonResponse(response_data, safe=False)


def api_job_result_pdf(request, job_uuid):
    try:
        job = models.Job.objects.get(job_uuid=job_uuid)
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "job with uuid={} does not exist.".format(job_uuid)}
        return JsonResponse(result, status=404)

    if not can_view_job(request.api_access, job):
        return _api_object_permission_denied("job")

    try:
        report_file, report_filename = open_job_report(job_uuid)
    except ArtifactUnavailable:
        return JsonResponse({"status": "error", "message": "pdf report does not exist"}, status=404)
    return FileResponse(
        report_file,
        content_type="application/pdf",
        as_attachment=True,
        filename=report_filename,
    )


def api_job_history(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    # Check delivery existence
    try:
        delivery = models.Delivery.objects.get(id=int(delivery_id))
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "delivery with id={} not found.".format(delivery_id)}
        return JsonResponse(result, status=404)

    if not can_view_delivery(request.api_access, delivery):
        return _api_object_permission_denied("delivery")

    # Delivery identity, not filename, defines the job-history boundary.
    # Different users (or repeat uploads) may legitimately use the same ZIP
    # name and must never have their histories merged.
    candidate_jobs = models.Job.objects.filter(
        delivery_id=delivery.pk,
    ).select_related("delivery__user__userprofile")
    visible_job_ids = [
        job.pk
        for job in candidate_jobs
        if can_view_job(request.api_access, job)
    ]
    jobs = models.Job.objects.filter(pk__in=visible_job_ids).order_by(
        "-date_created", "-job_uuid"
    )
    # Ensure job status is up-to-date
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)

    # Preserve the legacy compact job-history representation. New job creation
    # responses are canonical so their UUID can be used directly in routes.
    job_list = serialize_job_history(jobs, compact_uuid=True)
    result = {"status": "OK",
              "message": "Job history of delivery id={}".format(delivery_id),
              "data": job_list}
    return JsonResponse(result)
