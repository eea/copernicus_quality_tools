"""API delivery registration and listing endpoints."""

import logging
from pathlib import Path
from pathlib import PurePosixPath
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.dashboard.services.products import find_product_description
from qc_tool.frontend.dashboard.services.products import guess_product_ident
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import resolve_user_delivery_upload
from qc_tool.frontend.dashboard.services.s3 import inspect_s3_delivery
from qc_tool.frontend.dashboard.services.s3 import parse_s3_registration
from qc_tool.frontend.dashboard.services.s3 import S3RegistrationError
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    MAX_DELIVERY_OFFSET,
    MAX_DELIVERY_PAGE_SIZE,
    bounded_query_integer,
    query_deliveries,
)

from qc_tool.frontend.dashboard.views.api_access.shared import (
    API_JSON_MAX_BODY_BYTES,
    _json_request_error_response,
)

logger = logging.getLogger(__name__)


def api_register_delivery(request):
    user = request.api_user

    try:
        body_json = read_json_object(
            request,
            maximum_bytes=API_JSON_MAX_BODY_BYTES,
        )
    except JsonRequestError as exc:
        return _json_request_error_response(exc)

    try:
        target_filepath = resolve_user_delivery_upload(
            body_json.get("uploaded_file"),
            media_root=settings.MEDIA_ROOT,
            username=user.username,
        )
    except DeliveryUploadPathError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    # Assign product description based on product ident.
    # Typically, the product ident is used as the zip filename prefix.
    product_ident = guess_product_ident(target_filepath)
    logger.debug(product_ident)
    product_description = find_product_description(product_ident)

    # Register the uploaded file as a new delivery in the database.
    d = models.Delivery()
    d.filename = target_filepath.name
    d.size_bytes = target_filepath.stat().st_size
    d.product_ident = product_ident
    d.product_description = product_description
    d.date_uploaded = timezone.now()
    d.user = user
    d.is_deleted = False
    d.save()
    logger.debug("Delivery object saved successfully to database.")
    response_data = {"status": "ok", "message": "delivery successfully registered", "delivery_id": d.id}
    return JsonResponse(response_data, safe=False)


def api_register_delivery_s3(request):
    user = request.api_user

    try:
        body_json = read_json_object(
            request,
            maximum_bytes=API_JSON_MAX_BODY_BYTES,
        )
    except JsonRequestError as exc:
        return _json_request_error_response(exc)

    try:
        registration = parse_s3_registration(
            body_json,
            allowed_endpoints=settings.S3_ALLOWED_ENDPOINTS,
        )
        delivery = inspect_s3_delivery(
            registration,
            connect_timeout=settings.S3_CONNECT_TIMEOUT_SECONDS,
            read_timeout=settings.S3_READ_TIMEOUT_SECONDS,
            maximum_objects=settings.S3_MAX_LISTED_OBJECTS,
        )
    except S3RegistrationError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.message,
            },
            status=exc.status_code,
        )

    # Assign product description based on product ident.
    # Typically, the product ident should be contained in a user-defined filename pattern.
    delivery_filename = PurePosixPath(delivery.filename).name
    product_ident = guess_product_ident(Path(delivery_filename))
    logger.debug(product_ident)
    product_description = find_product_description(product_ident)

    # Register the S3 delivery as a new delivery in the database.
    with transaction.atomic():
        s3 = models.S3Info.objects.create(
            host=registration.endpoint,
            access_key=registration.access_key,
            secret_key=registration.secret_key,
            bucketname=registration.bucket_name,
            key_prefix=registration.key_prefix,
        )
        d = models.Delivery.objects.create(
            filename=delivery_filename,
            size_bytes=delivery.size_bytes,
            product_ident=product_ident,
            product_description=product_description,
            date_uploaded=timezone.now(),
            user=user,
            is_deleted=False,
            s3=s3,
        )
    logger.debug("Delivery object saved successfully to database.")
    response_data = {"status": "ok", "message": "S3 delivery successfully registered", "delivery_id": d.id}
    return JsonResponse(response_data, safe=False)


def api_delivery_list(request):
    """
       Returns a list of all deliveries for the current user.
       The deliveries are loaded from the dashboard_deliveries database table.
       The associated ZIP files are stored in <MEDIA_ROOT>/<username>/

       :param request:
       :return: list of deliveries with associated job information in JSON format
       """
    user = request.api_user

    # Retrieve query parameters (offset, limit).
    # Offset and limit must be positive numbers.
    offset = bounded_query_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = bounded_query_integer(
        request.GET.get("limit"),
        default=20,
        minimum=1,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )

    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    # filter and search are ignored by the API, they are used for UI only.
    filter = ""
    search = ""

    total, data = query_deliveries(
        user,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter=filter,
        search=search,
        account_access=request.api_access,
    )
    logger.debug("List of deliveries successfully obtained.")

    # next_offset is the link to the next page.
    if len(data) < limit:
        next_offset = 0
    else:
        next_offset = offset + limit

    response_data = {"status": "ok",
                     "message": "list of deliveries successfully obtained",
                     "total": total,
                     "offset": offset,
                     "limit": limit,
                     "next_offset": next_offset,
                     "deliveries": data}
    return JsonResponse(response_data, safe=False)
