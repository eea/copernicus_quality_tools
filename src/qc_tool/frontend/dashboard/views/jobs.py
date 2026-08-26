"""QC job setup, history, artifacts, and lifecycle endpoints."""

import logging
import time
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils import timezone
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.common import compose_job_log_filepath
from qc_tool.common import compose_job_stdout_filepath
from qc_tool.common import compile_job_form_data
from qc_tool.common import compile_job_report_data
from qc_tool.common import get_product_descriptions
from qc_tool.frontend.dashboard.access import can_view_job
from qc_tool.frontend.dashboard.access import require_delivery_view
from qc_tool.frontend.dashboard.access import require_job_view
from qc_tool.frontend.dashboard.services.configuration.presentation import (
    get_announcement_message,
)
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_job_attachment
from qc_tool.frontend.dashboard.services.artifacts import open_job_report
from qc_tool.frontend.dashboard.services.artifacts import read_text_artifact
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import JobDeletionError
from qc_tool.frontend.dashboard.services.jobs import delete_jobs_and_reproject
from qc_tool.frontend.dashboard.services.jobs import parse_batch_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.jobs import serialize_job_report
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import parse_positive_identifier_list
from qc_tool.frontend.dashboard.services.requests import parse_uuid_identifier_list

logger = logging.getLogger(__name__)

CHECK_RUNNING_JOB_DELAY = 10


def setup_job(request):
    """
    Displays a page for starting a new QA job
    :param delivery_id: The ID of the delivery ZIP file.
    """

    try:
        delivery_ids = parse_positive_identifier_list(
            request.GET.get("deliveries"),
        )
    except IdentifierListError as exc:
        return HttpResponseBadRequest(exc.message)

    product_infos = get_product_descriptions()
    product_list = [{"product_ident": product_ident, "product_description": product_name}
                    for product_ident, product_name in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x["product_description"])

    deliveries_by_id = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    if len(deliveries_by_id) != len(delivery_ids):
        raise Http404("One or more selected deliveries do not exist.")

    account_access = access_for_request(request)
    deliveries = []
    for delivery_id in delivery_ids:
        delivery = deliveries_by_id[delivery_id]

        # Starting a job for a submitted delivery is not permitted.
        if delivery.date_submitted is not None:
            raise PermissionDenied("Starting a new QC job on submitted delivery is not permitted.")

        if not account_access.can_manage_user(delivery.user_id):
            raise PermissionDenied("A selected delivery belongs to another user.")
        deliveries.append(delivery)

    # pass in product ident (only for the single delivery case)
    if len(deliveries) == 1:
        product_ident = deliveries[0].product_ident
    else:
        product_ident = None

    context = {"deliveries": deliveries,
               "product_ident": product_ident,
               "product_list": product_list,
               "show_logo": settings.SHOW_LOGO,
               "announcement": get_announcement_message()}
    return render(request, "dashboard/jobs/setup.html", context)


def job_delete(request):
    """
    Deletes the job from the database and associated files from the filesystem.
    """
    try:
        job_uuids = parse_uuid_identifier_list(request.POST.get("uuids"))
    except IdentifierListError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    try:
        deleted_count = delete_jobs_and_reproject(
            job_uuids,
            access_for_request(request),
        )
    except JobDeletionError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    return JsonResponse(
        {
            "status": "ok",
            "message": "{:d} jobs deleted successfully.".format(deleted_count),
        }
    )


def get_job_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of job steps and their type (system, required, optional)
    """
    job_report = compile_job_form_data(product_ident)
    return JsonResponse({'job_result': job_report})


def get_job_history_json(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

    account_access = access_for_request(request)
    require_delivery_view(account_access, delivery)

    # A job history belongs to one Delivery row. Filenames are not unique and
    # must never be used as an ownership or association boundary.
    candidate_jobs = models.Job.objects.filter(
        delivery_id=delivery.pk
    ).select_related("delivery__user__userprofile")
    visible_job_ids = [
        job.pk for job in candidate_jobs if can_view_job(account_access, job)
    ]
    jobs = models.Job.objects.filter(pk__in=visible_job_ids).order_by(
        "-date_created", "-job_uuid"
    )
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)
    return JsonResponse(serialize_job_history(jobs), safe=False)


def job_history_page(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    account_access = access_for_request(request)
    require_delivery_view(account_access, delivery)
    can_delete_jobs = bool(
        account_access.can_delete
        and account_access.can_manage_user(delivery.user_id)
    )
    return render(
        request,
        "dashboard/jobs/history.html",
        {
            "delivery": delivery,
            "show_logo": settings.SHOW_LOGO,
            "can_delete_jobs": can_delete_jobs,
        },
    )


def get_result(request, job_uuid):
    """
    Shows the result page with detailed results of the selected job.
    """
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    delivery = job.delivery
    job_report = serialize_job_report(
        compile_job_report_data(job_uuid, job.product_ident),
        job,
    )

    # if job status is not set in the report then try get status from the DB table (case of TIMEOUT or LOST)
    if job_report.get("status") is None:
        job_report["status"] = job.job_status

    for step in job_report["steps"]:
        # Strip initial qc_tool. from check idents.
        if step["check_ident"].startswith("qc_tool."):
            step["check_ident"] = ".".join(step["check_ident"].split(".")[1:])
        # Inform the result page about presence of a check with 'aborted' status.
        if step["status"] == "aborted":
            job_report["aborted_check"] = step["check_ident"]
    return render(request, "dashboard/jobs/result.html", {"job_report":job_report,
                                                     "delivery": delivery,
                                                     "show_logo": settings.SHOW_LOGO,
                                                     "announcement": get_announcement_message()
                                                     })


def get_pdf_report(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
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


def get_job_report(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    job_result = serialize_job_report(
        compile_job_report_data(job_uuid, job.product_ident),
        job,
    )
    return JsonResponse(job_result, safe=False)


def get_combined_job_log(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    stdout_filepath = compose_job_stdout_filepath(job_uuid)
    joblog_filepath = compose_job_log_filepath(job_uuid)

    stdout_log_text = "Loading stdout log .."
    joblog_log_text = "Loading job log .."
    try:
        stdout_log_text = read_text_artifact(
            stdout_filepath.parent,
            stdout_filepath.name,
        )
    except ArtifactUnavailable:
        stdout_log_text = "stdout log: no data."

    try:
        joblog_log_text = read_text_artifact(
            joblog_filepath.parent,
            joblog_filepath.name,
        )
    except ArtifactUnavailable:
        joblog_log_text = "job log: no data."

    combined_log = "STDOUT LOG:" + "\n" + stdout_log_text + "DETAILED JOB LOG:" + "\n" + joblog_log_text
    return HttpResponse(combined_log, content_type="text/plain")


def get_attachment(request, job_uuid, attachment_filename):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    try:
        attachment_file = open_job_attachment(job_uuid, attachment_filename)
    except ArtifactUnavailable:
        raise Http404()
    return FileResponse(
        attachment_file,
        as_attachment=True,
        filename=attachment_filename,
    )


def update_job(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)

    if job.job_status == JOB_RUNNING:
        time_running = (timezone.now() - job.date_started).total_seconds()
        if time_running > CHECK_RUNNING_JOB_DELAY:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)

    return JsonResponse({"id": job.delivery.id, "last_job_uuid": job.job_uuid, "last_job_status": job.job_status})


def create_job(request):
    try:
        job_request = parse_batch_job_creation_request(request.POST)
    except JobRequestError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    deliveries = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=job_request.delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    missing_ids = [
        delivery_id
        for delivery_id in job_request.delivery_ids
        if delivery_id not in deliveries
    ]
    if missing_ids:
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_not_found",
                "message": "One or more selected deliveries do not exist.",
            },
            status=404,
        )

    account_access = access_for_request(request)
    for delivery_id in job_request.delivery_ids:
        if not account_access.can_manage_user(deliveries[delivery_id].user_id):
            raise PermissionDenied(
                "A selected delivery belongs to another user."
            )

    try:
        with transaction.atomic():
            for delivery_id in job_request.delivery_ids:
                delivery = deliveries[delivery_id]
                delivery.create_job(
                    job_request.product_ident,
                    job_request.skip_steps,
                )
                logger.debug(
                    "Delivery %d: job has been submitted.",
                    delivery.id,
                )
    except Exception:
        logger.exception("A QC job batch could not be created.")
        return JsonResponse(
            {
                "status": "error",
                "code": "job_creation_failed",
                "message": "The QC jobs could not be created.",
            },
            status=500,
        )

    num_created = len(job_request.delivery_ids)
    if num_created == 1:
        msg = "QC Job has been set up for execution (product: {:s}).".format(
            job_request.product_ident
        )
    else:
        msg = "{:d} QC Jobs have been set up for execution (product: {:s}).".format(
            num_created,
            job_request.product_ident,
        )

    result = {"num_created": num_created, "status": "OK", "message": msg}
    return JsonResponse(result)


def refresh_job_statuses():
    # This function is running in a background thread, refreshing statuses of running jobs.
    time.sleep(10)
    while True:
        running_jobs = models.Job.objects.filter(job_status=JOB_RUNNING)
        logger.info("Found {:d} running jobs.".format(len(running_jobs)))
        updated_count = 0
        for job in running_jobs:
            time_running = (timezone.now() - job.date_started).total_seconds()
            if time_running > CHECK_RUNNING_JOB_DELAY:
                job_status = check_running_job(str(job.job_uuid), job.worker_url, CONFIG["worker_alive_timeout"])
                if job_status is not None:
                    if job_status != JOB_RUNNING:
                        job.update_status(job_status)
                        updated_count += 1
        logger.info("refresh_job_statuses: Status of {:d} running jobs has been updated.".format(updated_count))
        time.sleep(int(CONFIG["refresh_job_statuses_background_interval"]))
