"""Compatibility facade for API delivery endpoints.

The facade keeps the historic import and mock surface while endpoint behavior
is split between local registration, S3 registration, and listing modules.
"""

import logging
from pathlib import Path
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    MAX_DELIVERY_OFFSET,
    MAX_DELIVERY_PAGE_SIZE,
    bounded_query_integer,
    query_deliveries,
)
from qc_tool.frontend.dashboard.services.products import find_product_description
from qc_tool.frontend.dashboard.services.products import guess_product_ident
from qc_tool.frontend.dashboard.services.s3 import inspect_s3_delivery
from qc_tool.frontend.dashboard.services.s3 import parse_s3_registration
from qc_tool.frontend.dashboard.services.s3 import S3RegistrationError
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import resolve_user_delivery_upload
from qc_tool.frontend.dashboard.views.api_access.deliveries.listing import (
    list_deliveries,
)
from qc_tool.frontend.dashboard.views.api_access.deliveries.registration.local import (
    register_local_delivery,
)
from qc_tool.frontend.dashboard.views.api_access.deliveries.registration.s3 import (
    register_s3_delivery,
)
from qc_tool.frontend.dashboard.views.api_access.shared import (
    API_JSON_MAX_BODY_BYTES,
    _json_request_error_response,
)


logger = logging.getLogger(__name__)


@transaction.non_atomic_requests
def api_register_delivery(request):
    return register_local_delivery(
        request,
        maximum_body_bytes=API_JSON_MAX_BODY_BYTES,
        read_json=read_json_object,
        json_request_error_type=JsonRequestError,
        json_request_error_response=_json_request_error_response,
        resolve_upload=resolve_user_delivery_upload,
        upload_path_error_type=DeliveryUploadPathError,
        settings_module=settings,
        find_product=find_product_description,
        model_module=models,
        now=timezone.now,
        endpoint_logger=logger,
    )


def api_register_delivery_s3(request):
    return register_s3_delivery(
        request,
        maximum_body_bytes=API_JSON_MAX_BODY_BYTES,
        read_json=read_json_object,
        json_request_error_type=JsonRequestError,
        json_request_error_response=_json_request_error_response,
        parse_registration=parse_s3_registration,
        inspect_delivery=inspect_s3_delivery,
        registration_error_type=S3RegistrationError,
        settings_module=settings,
        find_product=find_product_description,
        model_module=models,
        atomic=transaction.atomic,
        now=timezone.now,
        endpoint_logger=logger,
    )


def api_delivery_list(request):
    return list_deliveries(
        request,
        max_offset=MAX_DELIVERY_OFFSET,
        max_page_size=MAX_DELIVERY_PAGE_SIZE,
        parse_bounded_integer=bounded_query_integer,
        query_delivery_rows=query_deliveries,
        endpoint_logger=logger,
    )


__all__ = (
    "api_delivery_list",
    "api_register_delivery",
    "api_register_delivery_s3",
)
