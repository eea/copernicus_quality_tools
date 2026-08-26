"""Registration of an uploaded local delivery archive."""

from django.http import JsonResponse


def register_local_delivery(
    request,
    *,
    maximum_body_bytes,
    read_json,
    json_request_error_type,
    json_request_error_response,
    resolve_upload,
    upload_path_error_type,
    settings_module,
    guess_product,
    find_product,
    model_module,
    now,
    endpoint_logger,
):
    user = request.api_user
    try:
        body_json = read_json(
            request,
            maximum_bytes=maximum_body_bytes,
        )
    except json_request_error_type as exc:
        return json_request_error_response(exc)

    try:
        target_filepath = resolve_upload(
            body_json.get("uploaded_file"),
            media_root=settings_module.MEDIA_ROOT,
            username=user.username,
        )
    except upload_path_error_type as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )

    product_ident = guess_product(target_filepath)
    endpoint_logger.debug(product_ident)
    product_description = find_product(product_ident)

    delivery = model_module.Delivery()
    delivery.filename = target_filepath.name
    delivery.size_bytes = target_filepath.stat().st_size
    delivery.product_ident = product_ident
    delivery.product_description = product_description
    delivery.date_uploaded = now()
    delivery.user = user
    delivery.is_deleted = False
    delivery.save()
    endpoint_logger.debug("Delivery object saved successfully to database.")
    response_data = {
        "status": "ok",
        "message": "delivery successfully registered",
        "delivery_id": delivery.id,
    }
    return JsonResponse(response_data, safe=False)
