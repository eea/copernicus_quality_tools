"""API QC job creation endpoint behavior."""

from django.http import JsonResponse


def create_job(
    request,
    *,
    maximum_body_bytes,
    read_json,
    json_request_error_type,
    json_request_error_response,
    parse_creation_request,
    job_request_error_type,
    model_module,
    normalize_uuid,
):
    try:
        body_json = read_json(
            request,
            maximum_bytes=maximum_body_bytes,
        )
        job_request = parse_creation_request(body_json)
    except json_request_error_type as exc:
        return json_request_error_response(exc)
    except job_request_error_type as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.message,
            },
            status=400,
        )

    try:
        delivery = model_module.Delivery.objects.get(
            id=job_request.delivery_id,
        )
    except model_module.Delivery.DoesNotExist:
        result = {
            "status": "error",
            "message": "delivery with id={} not found.".format(
                job_request.delivery_id
            ),
        }
        return JsonResponse(result, status=404)

    # Scoped managers may read other users' deliveries, but only an owner or
    # administrator may mutate one.
    if not request.api_access.can_manage_user(delivery.user_id):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot modify this delivery.",
            },
            status=403,
        )

    try:
        job_uuid = delivery.create_job(
            job_request.product_ident,
            job_request.skip_steps,
            requested_by=request.api_user,
            request_source="api",
            api_token=request.api_token,
            account_access=request.api_access,
        )
    except PermissionError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": str(exc),
            },
            status=403,
        )
    except ValueError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_not_eligible_for_qc",
                "message": str(exc),
            },
            status=409,
        )

    response_data = {"job_uuid": normalize_uuid(job_uuid)}
    result = {
        "status": "OK",
        "message": "QC job successfully created",
        "data": response_data,
    }
    return JsonResponse(result)
