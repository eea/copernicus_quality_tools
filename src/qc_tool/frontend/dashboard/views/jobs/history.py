"""Job-history page and JSON endpoint."""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.access import can_view_job
from qc_tool.frontend.dashboard.access import require_delivery_view
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.jobs.presentation import (
    job_history_delivery_summary,
)


def get_job_history_json(request, delivery_id):
    """Return the visible QC history associated with one Delivery row."""

    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    account_access = access_for_request(request)
    require_delivery_view(account_access, delivery)

    # Filenames are not unique and must never be an association boundary.
    candidate_jobs = models.Job.objects.filter(
        delivery_id=delivery.pk
    ).select_related("delivery__user", "product_release__product")
    visible_job_ids = [
        job.pk for job in candidate_jobs if can_view_job(account_access, job)
    ]
    jobs = models.Job.objects.filter(pk__in=visible_job_ids).order_by(
        "-date_created",
        "-job_uuid",
    )
    _refresh_running_jobs(jobs)
    rows = serialize_job_history(jobs)
    if request.GET.get("include_delivery") == "1":
        # Updating a running job can also refresh the delivery's projected
        # product/product unit facts. Read them again before building the live header.
        delivery.refresh_from_db()
        return JsonResponse({
            "rows": rows,
            "delivery_summary": job_history_delivery_summary(delivery, account_access),
        })
    return JsonResponse(rows, safe=False)


def job_history_page(request, delivery_id):
    """Render the job history page for one authorized delivery."""

    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    account_access = access_for_request(request)
    require_delivery_view(account_access, delivery)
    return render(
        request,
        "dashboard/jobs/history.html",
        {
            "delivery": delivery,
            "delivery_summary": job_history_delivery_summary(delivery, account_access),
        },
    )


def _refresh_running_jobs(jobs):
    for job in jobs:
        if job.job_status != JOB_RUNNING:
            continue
        job_status = check_running_job(
            str(job.job_uuid),
            job.worker_url,
            CONFIG["worker_alive_timeout"],
        )
        if job_status is not None:
            job.update_status(job_status)
