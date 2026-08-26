"""API delivery job-history endpoint behavior."""

from django.http import JsonResponse


def job_history(
    request,
    delivery_id,
    *,
    model_module,
    object_does_not_exist,
    can_view_delivery,
    can_view_job,
    permission_denied,
    running_status,
    refresh_running_job,
    configuration,
    serialize_history,
):
    """Show all visible jobs for one delivery as JSON."""
    try:
        delivery = model_module.Delivery.objects.get(id=int(delivery_id))
    except object_does_not_exist:
        result = {
            "status": "error",
            "message": "delivery with id={} not found.".format(delivery_id),
        }
        return JsonResponse(result, status=404)

    if not can_view_delivery(request.api_access, delivery):
        return permission_denied("delivery")

    # Delivery identity, not filename, defines the job-history boundary.
    candidate_jobs = model_module.Job.objects.filter(
        delivery_id=delivery.pk,
    ).select_related("delivery__user__userprofile")
    visible_job_ids = [
        job.pk
        for job in candidate_jobs
        if can_view_job(request.api_access, job)
    ]
    jobs = model_module.Job.objects.filter(pk__in=visible_job_ids).order_by(
        "-date_created",
        "-job_uuid",
    )

    for job in jobs:
        if job.job_status == running_status:
            job_status = refresh_running_job(
                str(job.job_uuid),
                job.worker_url,
                configuration["worker_alive_timeout"],
            )
            if job_status is not None:
                job.update_status(job_status)

    job_list = serialize_history(jobs, compact_uuid=True)
    result = {
        "status": "OK",
        "message": "Job history of delivery id={}".format(delivery_id),
        "data": job_list,
    }
    return JsonResponse(result)
