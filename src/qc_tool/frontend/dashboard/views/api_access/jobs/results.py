"""API QC job JSON and PDF result endpoint behavior."""

from django.http import JsonResponse


def _load_visible_job(
    request,
    job_uuid,
    *,
    model_module,
    object_does_not_exist,
    can_view,
    permission_denied,
):
    try:
        job = model_module.Job.objects.get(job_uuid=job_uuid)
    except object_does_not_exist:
        result = {
            "status": "error",
            "message": "job with uuid={} does not exist.".format(job_uuid),
        }
        return None, JsonResponse(result, status=404)

    if not can_view(request.api_access, job):
        return None, permission_denied("job")
    return job, None


def job_result(
    request,
    job_uuid,
    *,
    model_module,
    object_does_not_exist,
    can_view,
    permission_denied,
    compile_report,
    serialize_report,
):
    job, error_response = _load_visible_job(
        request,
        job_uuid,
        model_module=model_module,
        object_does_not_exist=object_does_not_exist,
        can_view=can_view,
        permission_denied=permission_denied,
    )
    if error_response is not None:
        return error_response

    job_report = serialize_report(
        compile_report(job_uuid, job.product_ident),
        job,
    )
    response_data = {
        "status": "ok",
        "message": "job status",
        "data": job_report,
    }
    return JsonResponse(response_data, safe=False)


def job_result_pdf(
    request,
    job_uuid,
    *,
    model_module,
    object_does_not_exist,
    can_view,
    permission_denied,
    open_report,
    artifact_unavailable,
    file_response,
):
    _job, error_response = _load_visible_job(
        request,
        job_uuid,
        model_module=model_module,
        object_does_not_exist=object_does_not_exist,
        can_view=can_view,
        permission_denied=permission_denied,
    )
    if error_response is not None:
        return error_response

    try:
        report_file, report_filename = open_report(job_uuid)
    except artifact_unavailable:
        return JsonResponse(
            {"status": "error", "message": "pdf report does not exist"},
            status=404,
        )
    return file_response(
        report_file,
        content_type="application/pdf",
        as_attachment=True,
        filename=report_filename,
    )
