"""Job status polling endpoint and background refresher."""

import logging
import time

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.access import require_job_view


logger = logging.getLogger(__name__)

CHECK_RUNNING_JOB_DELAY = 10


def update_job(request, job_uuid):
    """Refresh and return the current status of one authorized job."""

    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    _refresh_if_stale(job)
    return JsonResponse(
        {
            "id": job.delivery.id,
            "last_job_uuid": job.job_uuid,
            "last_job_status": job.job_status,
        }
    )


def refresh_job_statuses():
    """Continuously refresh running jobs from the worker status API."""

    time.sleep(10)
    while True:
        running_jobs = models.Job.objects.filter(job_status=JOB_RUNNING)
        logger.info("Found %d running jobs.", len(running_jobs))
        updated_count = 0
        for job in running_jobs:
            previous_status = job.job_status
            _refresh_if_stale(job)
            if previous_status == JOB_RUNNING and job.job_status != JOB_RUNNING:
                updated_count += 1
        logger.info(
            "refresh_job_statuses: Status of %d running jobs has been updated.",
            updated_count,
        )
        time.sleep(int(CONFIG["refresh_job_statuses_background_interval"]))


def _refresh_if_stale(job):
    if job.job_status != JOB_RUNNING:
        return
    time_running = (timezone.now() - job.date_started).total_seconds()
    if time_running <= CHECK_RUNNING_JOB_DELAY:
        return
    job_status = check_running_job(
        str(job.job_uuid),
        job.worker_url,
        CONFIG["worker_alive_timeout"],
    )
    if job_status is not None:
        job.update_status(job_status)
