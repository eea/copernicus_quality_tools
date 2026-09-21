"""Registration of a validated S3-backed delivery."""

from pathlib import PurePosixPath

from django.http import JsonResponse
from qc_tool.frontend.dashboard.services.uploads.access import require_upload_product, require_upload_filename
from qc_tool.frontend.dashboard.services.uploads.resumable import ResumableUploadError
from qc_tool.frontend.dashboard.services.s3.credentials import (
    S3CredentialsUnavailable, discard_s3_credentials, store_s3_credentials,
)


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
    try:
        product_ident = require_upload_filename(
            request.api_access, delivery_filename,
        ).product_ident
        require_upload_product(request.api_access, product_ident)
    except ResumableUploadError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    endpoint_logger.debug(product_ident)
    product_description = find_product(product_ident)

    try:
        credential_ref = store_s3_credentials(registration)
    except S3CredentialsUnavailable:
        return JsonResponse(
            {"status": "error", "code": "s3_credentials_unavailable",
             "message": "S3 credentials could not be stored. Contact an administrator."},
            status=503,
        )
    try:
        with atomic():
            s3 = model_module.S3Info.objects.create(
                host=registration.endpoint,
                credential_ref=credential_ref,
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
    except Exception:
        try:
            discard_s3_credentials(credential_ref)
        except S3CredentialsUnavailable:
            endpoint_logger.error("Could not clean up credentials after failed S3 registration.")
        raise
    endpoint_logger.debug("Delivery object saved successfully to database.")
    response_data = {
        "status": "ok",
        "message": "S3 delivery successfully registered",
        "delivery_id": delivery_record.id,
    }
    return JsonResponse(response_data, safe=False)
