"""Registration of a validated S3-backed delivery."""

from pathlib import Path
from pathlib import PurePosixPath

from django.http import JsonResponse
from qc_tool.frontend.dashboard.services.uploads.access import require_upload_product
from qc_tool.frontend.dashboard.services.uploads.resumable import ResumableUploadError


def register_s3_delivery(
    request,
    *,
    maximum_body_bytes,
    read_json,
    json_request_error_type,
    json_request_error_response,
    parse_registration,
    inspect_delivery,
    registration_error_type,
    settings_module,
    guess_product,
    find_product,
    model_module,
    atomic,
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
        registration = parse_registration(
            body_json,
            allowed_endpoints=settings_module.S3_ALLOWED_ENDPOINTS,
        )
        require_upload_product(request.api_access, None)
        delivery = inspect_delivery(
            registration,
            connect_timeout=settings_module.S3_CONNECT_TIMEOUT_SECONDS,
            read_timeout=settings_module.S3_READ_TIMEOUT_SECONDS,
            maximum_objects=settings_module.S3_MAX_LISTED_OBJECTS,
        )
    except (registration_error_type, ResumableUploadError) as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.message,
            },
            status=exc.status_code,
        )

    delivery_filename = PurePosixPath(delivery.filename).name
    product_ident = guess_product(Path(delivery_filename))
    try:
        require_upload_product(request.api_access, product_ident)
    except ResumableUploadError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    endpoint_logger.debug(product_ident)
    product_description = find_product(product_ident)

    with atomic():
        s3 = model_module.S3Info.objects.create(
            host=registration.endpoint,
            access_key=registration.access_key,
            secret_key=registration.secret_key,
            bucketname=registration.bucket_name,
            key_prefix=registration.key_prefix,
        )
        delivery_record = model_module.Delivery.objects.create(
            filename=delivery_filename,
            size_bytes=delivery.size_bytes,
            product_ident=product_ident,
            product_description=product_description,
            date_uploaded=now(),
            user=user,
            is_deleted=False,
            s3=s3,
        )
    endpoint_logger.debug("Delivery object saved successfully to database.")
    response_data = {
        "status": "ok",
        "message": "S3 delivery successfully registered",
        "delivery_id": delivery_record.id,
    }
    return JsonResponse(response_data, safe=False)
