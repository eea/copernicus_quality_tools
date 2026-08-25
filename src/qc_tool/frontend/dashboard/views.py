# -*- coding: utf-8 -*-


import io
import logging
import os
import time
from pathlib import Path
from pathlib import PurePosixPath
import uuid
import json

import openpyxl

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils import timezone

import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.accounts.authentication.api_keys import has_api_key
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.common import compose_job_log_filepath
from qc_tool.common import compose_job_stdout_filepath
from qc_tool.common import compile_job_form_data
from qc_tool.common import compile_job_report_data
from qc_tool.common import get_product_descriptions
from qc_tool.common import locate_product_definition
from qc_tool.common import WORKER_PORT
from qc_tool.frontend.dashboard.access import can_view_job
from qc_tool.frontend.dashboard.access import can_view_delivery
from qc_tool.frontend.dashboard.access import delivery_action_capabilities
from qc_tool.frontend.dashboard.access import require_delivery_view
from qc_tool.frontend.dashboard.access import require_job_view
from qc_tool.frontend.dashboard.helpers import find_product_description
from qc_tool.frontend.dashboard.helpers import get_announcement_message
from qc_tool.frontend.dashboard.helpers import guess_product_ident
from qc_tool.frontend.dashboard.helpers import submit_job
from qc_tool.frontend.dashboard.helpers import get_boundary_version
from qc_tool.frontend.dashboard.services.boundaries import BoundaryPackageError
from qc_tool.frontend.dashboard.services.boundaries import replace_boundary_package
from qc_tool.frontend.dashboard.services.boundaries import resolve_boundary_generation
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_job_attachment
from qc_tool.frontend.dashboard.services.artifacts import open_job_report
from qc_tool.frontend.dashboard.services.artifacts import open_regular_artifact
from qc_tool.frontend.dashboard.services.artifacts import read_text_artifact
from qc_tool.frontend.dashboard.services.configuration import AnnouncementStorageError
from qc_tool.frontend.dashboard.services.configuration import read_announcement
from qc_tool.frontend.dashboard.services.configuration import write_announcement
from qc_tool.frontend.dashboard.services.deliveries import summarize_deliveries
from qc_tool.frontend.dashboard.services.exports import spreadsheet_cell_value
from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import parse_batch_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import parse_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import positive_identifier
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadError
from qc_tool.frontend.dashboard.services.uploads import assemble_chunks
from qc_tool.frontend.dashboard.services.uploads import is_chunk_stored
from qc_tool.frontend.dashboard.services.uploads import is_upload_complete
from qc_tool.frontend.dashboard.services.uploads import prepare_resumable_paths
from qc_tool.frontend.dashboard.services.uploads import remove_published_upload
from qc_tool.frontend.dashboard.services.uploads import remove_user_delivery_upload
from qc_tool.frontend.dashboard.services.uploads import resolve_user_delivery_upload
from qc_tool.frontend.dashboard.services.uploads import store_chunk
from qc_tool.frontend.dashboard.services.s3 import inspect_s3_delivery
from qc_tool.frontend.dashboard.services.s3 import parse_s3_registration
from qc_tool.frontend.dashboard.services.s3 import S3RegistrationError
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import parse_positive_identifier_list
from qc_tool.frontend.dashboard.services.requests import parse_uuid_identifier_list
from qc_tool.worker_auth import InvalidWorkerUrl
from qc_tool.worker_auth import worker_origin_from_remote_address

logger = logging.getLogger(__name__)

CHECK_RUNNING_JOB_DELAY = 10
MAX_DELIVERY_PAGE_SIZE = 1_000
MAX_DELIVERY_OFFSET = 10_000_000


API_JSON_MAX_BODY_BYTES = 16 * 1024


def _json_request_error_response(error):
    return JsonResponse(
        {
            "status": "error",
            "code": error.code,
            "message": error.message,
        },
        status=error.status_code,
    )

def api_homepage(request):
    return render(
        request,
        "dashboard/api_docs.html",
        {"api_url": CONFIG["api_url"]},
    )

def api_openapi_json(request):
    api_url = CONFIG["api_url"]
    openapi_json_path = os.path.join(settings.BASE_DIR, "frontend", "dashboard", "static", "dashboard", "api", "openapi.json")
    with open(openapi_json_path, "r") as f:
        openapi_dict = json.load(f)
        openapi_dict["servers"][0]["url"] = api_url
        return JsonResponse(openapi_dict)

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
    offset = _bounded_query_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = _bounded_query_integer(
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

    total, data = query_deliveries(user, offset=offset, limit=limit,
                                   sort=sort, order=order, filter=filter, search=search)
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


def api_product_list(request):
    product_infos = get_product_descriptions()
    product_list = [{"product_ident": product_ident, "description": product_description}
                    for product_ident, product_description in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x["product_ident"])
    return JsonResponse({"products": product_list})


def api_product_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of job steps and their type (system, required, optional)
    """
    job_form_data = compile_job_form_data(product_ident)
    response_data = {"status": "ok", "message": f"showing available checks for {product_ident}", "data": job_form_data}
    return JsonResponse(response_data, safe=False)

def api_create_job(request):
    try:
        body_json = read_json_object(
            request,
            maximum_bytes=API_JSON_MAX_BODY_BYTES,
        )
        job_request = parse_job_creation_request(body_json)
    except JsonRequestError as exc:
        return _json_request_error_response(exc)
    except JobRequestError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.message,
            },
            status=400,
        )

    # Update delivery status in the frontend database.
    try:
        d = models.Delivery.objects.get(id=job_request.delivery_id)
    except ObjectDoesNotExist:
        result = {
            "status": "error",
            "message": "delivery with id={} not found.".format(
                job_request.delivery_id
            ),
        }
        return JsonResponse(result, status=404)

    # Scoped managers may read other users' deliveries, but only an owner or
    # administrator may mutate one.
    if not request.api_access.can_manage_user(d.user_id):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot modify this delivery.",
            },
            status=403,
        )

    job_uuid = d.create_job(
        job_request.product_ident,
        job_request.skip_steps,
    )

    response_data = {"job_uuid": str(job_uuid)}
    result = {"status": "OK", "message": "QC job successfully created", "data": response_data}
    return JsonResponse(result)

def api_job_result(request, job_uuid):
    try:
        job = models.Job.objects.get(job_uuid=job_uuid)
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "job with uuid={} does not exist.".format(job_uuid)}
        return JsonResponse(result, status=404)

    if not can_view_job(request.api_access, job):
        return _api_object_permission_denied("job")

    job_report = compile_job_report_data(job_uuid, job.product_ident)
    response_data = {"status": "ok", "message": "job status", "data": job_report}
    return JsonResponse(response_data, safe=False)

def api_job_result_pdf(request, job_uuid):
    try:
        job = models.Job.objects.get(job_uuid=job_uuid)
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "job with uuid={} does not exist.".format(job_uuid)}
        return JsonResponse(result, status=404)

    if not can_view_job(request.api_access, job):
        return _api_object_permission_denied("job")

    try:
        report_file, report_filename = open_job_report(job_uuid)
    except ArtifactUnavailable:
        return JsonResponse({"status": "error", "message": "pdf report does not exist"}, status=404)
    return FileResponse(
        report_file,
        content_type="application/pdf",
        as_attachment=True,
        filename=report_filename,
    )


def api_job_history(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    # Check delivery existence
    try:
        delivery = models.Delivery.objects.get(id=int(delivery_id))
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "delivery with id={} not found.".format(delivery_id)}
        return JsonResponse(result, status=404)

    if not can_view_delivery(request.api_access, delivery):
        return _api_object_permission_denied("delivery")

    candidate_jobs = models.Job.objects.filter(
        delivery__filename=delivery.filename,
    ).select_related("delivery__user__userprofile")
    visible_job_ids = [
        job.pk
        for job in candidate_jobs
        if can_view_job(request.api_access, job)
    ]
    jobs = models.Job.objects.filter(pk__in=visible_job_ids).order_by(
        "-date_created"
    )
    # Ensure job status is up-to-date
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)

    # Remove "-" characters from job uuids
    job_list = serialize_job_history(jobs, compact_uuid=True)
    result = {"status": "OK",
              "message": "Job history of delivery id={}".format(delivery_id),
              "data": job_list}
    return JsonResponse(result)


def _api_object_permission_denied(object_name):
    return JsonResponse(
        {
            "status": "error",
            "code": "object_permission_denied",
            "message": f"The account cannot access this {object_name}.",
        },
        status=403,
    )


def deliveries(request):
    """
    Displays the main page with uploaded files and action buttons
    """

    api_key_configured = has_api_key(request.user)
    update_job_statuses = CONFIG.get("update_job_statuses", True)
    update_job_statuses_interval = CONFIG.get("update_job_statuses_interval", 30000)

    return render(request, 'dashboard/deliveries.html', {"submission_enabled": settings.SUBMISSION_ENABLED,
                                                         "announcement": get_announcement_message(),
                                                         "boundary_version": get_boundary_version(),
                                                         "api_key_configured": api_key_configured,
                                                         "update_job_statuses": update_job_statuses,
                                                         "update_job_statuses_interval": update_job_statuses_interval})


def setup_job(request):
    """
    Displays a page for starting a new QA job
    :param delivery_id: The ID of the delivery ZIP file.
    """

    try:
        delivery_ids = parse_positive_identifier_list(
            request.GET.get("deliveries"),
        )
    except IdentifierListError as exc:
        return HttpResponseBadRequest(exc.message)

    product_infos = get_product_descriptions()
    product_list = [{"product_ident": product_ident, "product_description": product_name}
                    for product_ident, product_name in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x["product_description"])

    deliveries_by_id = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    if len(deliveries_by_id) != len(delivery_ids):
        raise Http404("One or more selected deliveries do not exist.")

    account_access = access_for_request(request)
    deliveries = []
    for delivery_id in delivery_ids:
        delivery = deliveries_by_id[delivery_id]

        # Starting a job for a submitted delivery is not permitted.
        if delivery.date_submitted is not None:
            raise PermissionDenied("Starting a new QC job on submitted delivery is not permitted.")

        if not account_access.can_manage_user(delivery.user_id):
            raise PermissionDenied("A selected delivery belongs to another user.")
        deliveries.append(delivery)

    # pass in product ident (only for the single delivery case)
    if len(deliveries) == 1:
        product_ident = deliveries[0].product_ident
    else:
        product_ident = None

    context = {"deliveries": deliveries,
               "product_ident": product_ident,
               "product_list": product_list,
               "show_logo": settings.SHOW_LOGO,
               "announcement": get_announcement_message()}
    return render(request, "dashboard/setup_job.html", context)


def parse_filter(filter_str, column_lookup):
    filter_sql = ""
    filter_params = []
    try:
        filter_dict = json.loads(filter_str)
    except json.JSONDecodeError:
        logger.warning("Unable to decode filter expression %r", filter_str)
        return "", []

    if not isinstance(filter_dict, dict):
        logger.warning("Filter expression must be a JSON object: %r", filter_str)
        return "", []

    for key, val in filter_dict.items():
        filter_column = column_lookup.get(key)
        if not filter_column:
            # ignore any undefined filter columns
            continue
        if key == "product_description":
            filter_sql += f" AND {filter_column} = %s"
            filter_params.append(val)
        elif key == "last_job_status":
            if val == "Not checked":
                filter_sql += f" AND {filter_column} IS NULL"
            else:
                filter_sql += f" AND {filter_column} = %s"
                filter_params.append(val)
        else:
            filter_sql += f" AND {filter_column} LIKE %s"
            filter_params.append(f"%{val}%")
    return filter_sql, filter_params


def _bounded_query_integer(value, *, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def query_deliveries(
    user,
    offset=0,
    limit=20,
    sort="id",
    order="desc",
    filter="",
    search="",
    include_capabilities=False,
    account_access=None,
):
    offset = _bounded_query_integer(
        offset,
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = _bounded_query_integer(
        limit,
        default=20,
        minimum=0,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )
    # Retrieve a table of deliveries.
    # If a delivery has one or more jobs, show information about the job with latest date_created.
    column_lookup = {
        "id": "d.id",
        "name": "d.id",
        "type": "d.s3_id",
        "filename": "d.filename",
        "date_uploaded": "d.date_uploaded",
        "size_bytes": "d.size_bytes",
        "product_ident": "d.product_ident",
        "product_description": "d.product_description",
        "date_submitted": "d.date_submitted",
        "is_deleted": "d.is_deleted",
        "product_ident": "d.product_ident",
        "date_submitted": "d.date_submitted",
        "date_created": "j.date_created",
        "date_started": "j.date_started",
        "last_job_status": "j.job_status",
        "last_job_uuid": "j.job_uuid",
        "username": "u.username",
        "user": "u.username"}

    # Lookup sort column, if not found then sort by id (default)
    sort_column = column_lookup.get(sort, "d.id")

    # Order asc or desc, must be asc or desc, default is desc
    order = order.strip().lower()
    if order not in ("asc", "desc"):
        order = "desc"

    # Assemble SQL filtering and/or searching
    filter_sql = ""
    filter_params = []
    if filter:
        filter_sql, filter_params = parse_filter(filter, column_lookup)

    # searching is done on filename column only.
    search_sql = ""
    search_params = []
    if search:
        search_sql = " AND d.filename LIKE %s"
        search_params.append(f"%{search}%")

    # Assemble SQL queries
    sql = """
        SELECT d.id, d.user_id AS action_owner_id, d.filename, u.username,
        d.date_uploaded, d.size_bytes,
        d.product_ident, d.product_description, d.date_submitted, d.is_deleted,
        d.s3_id,
        j.job_uuid AS last_job_uuid,
        j.date_created, j.date_started, j.job_status as last_job_status,
        up.country AS user_country
        FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
        ON j.job_uuid = (
          SELECT job_uuid FROM dashboard_job j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC, j.job_uuid DESC LIMIT 1)
        INNER JOIN auth_user u
        ON d.user_id = u.id
        LEFT JOIN dashboard_userprofile up
        ON d.user_id = up.user_id
        WHERE d.is_deleted = FALSE
        """
    sql_total = """
        SELECT COUNT(d.id)
        FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
        ON j.job_uuid = (
          SELECT job_uuid FROM dashboard_job j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC, j.job_uuid DESC LIMIT 1)
        INNER JOIN auth_user u
        ON d.user_id = u.id
        LEFT JOIN dashboard_userprofile up
        ON d.user_id = up.user_id
        WHERE d.is_deleted = FALSE
        """

    account_access = account_access or access_for(user)
    visibility_params = []

    if not account_access.is_administrator:
        visibility_clauses = ["d.user_id = %s"]
        visibility_params.append(user.id)
        if account_access.can_view_region_deliveries:
            # Compatibility until deliveries reference AOIs directly.
            region_codes = sorted(account_access.region_codes)
            placeholders = ", ".join(["%s"] * len(region_codes))
            visibility_clauses.append(
                f"up.country IN ({placeholders})"
            )
            visibility_params.extend(region_codes)
        if account_access.can_view_product_deliveries:
            product_idents = sorted(account_access.product_idents)
            placeholders = ", ".join(["%s"] * len(product_idents))
            visibility_clauses.append(
                f"LOWER(d.product_ident) IN ({placeholders})"
            )
            visibility_params.extend(product_idents)

        visibility_sql = " AND ({})".format(
            " OR ".join(visibility_clauses)
        )
        sql += visibility_sql
        sql_total += visibility_sql

    # Add filter expression and search expressions to sql queries
    sql_total += filter_sql
    sql_total += search_sql
    sql += filter_sql
    sql += search_sql
    query_params = visibility_params + filter_params + search_params

    # Add sort, offset and limit to sql query (with assigned or default values)
    sql += f" ORDER BY {sort_column} {order} LIMIT {limit} OFFSET {offset};"

    with connection.cursor() as cursor:
        # fetch total rows
        cursor.execute(sql_total, query_params)
        total_result = cursor.fetchone()
        total = int(total_result[0])

        # fetch query results
        cursor.execute(sql, query_params)

        # arrange the results
        header = [i[0] for i in cursor.description]
        rows = cursor.fetchall()
        data = []
        for row in rows:
            data.append(dict(zip(header, row)))

        # Add calculated "type" column to indicate if the file is local upload or s3.
        for item in data:
            if item["s3_id"]:
                item["type"] = "s3"
            else:
                item["type"] = "local"
            owner_id = item.pop("action_owner_id")
            if include_capabilities:
                item.update(
                    delivery_action_capabilities(account_access, owner_id)
                )
        return total, data


def get_deliveries_json(request):
    """
    Returns a list of all deliveries for the current user.
    The deliveries are loaded from the dashboard_deliveries database table.
    The associated ZIP files are stored in <MEDIA_ROOT>/<username>/

    :param request:
    :return: list of deliveries with associated job information in JSON format
    """
    offset = _bounded_query_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = _bounded_query_integer(
        request.GET.get("limit"),
        default=100,
        minimum=0,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )
    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    filter = request.GET.get("filter", "")
    search = request.GET.get("search", "")

    account_access = access_for_request(request)
    total, data = query_deliveries(
        request.user,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter=filter,
        search=search,
        include_capabilities=True,
        account_access=account_access,
    )

    delivery_summary = summarize_deliveries(account_access)
    return JsonResponse(
        {
            "total": total,
            "rows": data,
            "summary": delivery_summary.as_dict(),
        }
    )


def export_deliveries_excel(request):
    """
    Exports deliveries (filtered/sorted like get_deliveries_json)
    into an Excel (.xlsx) file and returns it as a download.
    """
    # Same parameters as JSON endpoint
    offset = _bounded_query_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = _bounded_query_integer(
        request.GET.get("limit"),
        default=1_000,
        minimum=0,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )
    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    filter = request.GET.get("filter", "")
    search = request.GET.get("search", "")

    # Get data using your existing query function
    _, data = query_deliveries(
        request.user,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter="",
        search=""
    )
    # Create a new Excel workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deliveries"

    if not data:
        ws.append(["No data found"])
    else:
        # Write header
        headers = list(data[0].keys())
        ws.append(headers)
        # Write rows in compatible format (e.g. convert UUIDs to strings)
        for row in data:
            formatted_row = []
            for col in headers:
                value = row.get(col, "")
                if isinstance(value, uuid.UUID):
                    value = str(value)
                formatted_row.append(spreadsheet_cell_value(value))
            ws.append(formatted_row)

    # Adjust column widths
    for col in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 60)

    # Save workbook to in-memory buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = "attachment; filename=deliveries.xlsx"
    return response


def resumable_upload_page(request):
    """
    Resumable file upload demo.
    """
    return render(request, 'dashboard/resumable_upload.html', {
        'resumable_simultaneous_uploads': settings.RESUMABLE_SIMULTANEOUS_UPLOADS
    })


def announcement(request):
    """
    Saves or loads an announcement message.
    """
    if request.method == "GET":
        try:
            announcement_message = read_announcement(
                CONFIG["announcement_path"]
            )
        except AnnouncementStorageError:
            logger.warning("Announcement state could not be read safely.")
            announcement_message = ""

        return render(request, 'dashboard/announcement.html', {"announcement": announcement_message})
    else:
        announcement_text = request.POST.get("announcement_text", "")
        try:
            write_announcement(
                CONFIG["announcement_path"],
                announcement_text,
            )
            if announcement_text:
                result_message = "Announcement has been successfully updated."
            else:
                result_message = "Announcement has been successfully removed."
            return render(request, 'dashboard/announcement.html',
                          {"announcement": announcement_text,
                           "result_message": result_message})
        except AnnouncementStorageError:
            logger.warning("Announcement update was rejected by safe storage.")
            return render(request, 'dashboard/announcement.html',
                          {"announcement": announcement_text,
                           "error_message": "Error updating announcement."})


def boundaries(request):
    """
    Returns a list of all boundary aoi files in the active boundary package in html format.
    """
    return render(request, 'dashboard/boundaries.html', {})


def get_boundaries_json(request, boundary_type):
    """
    Returns a list of all boundary aoi files in the active boundary package in json format.

    :param request:
    :return: list of boundary .tif or .shp file infos with name and size in JSON format
    """
    boundary_list = []
    try:
        generation = resolve_boundary_generation(CONFIG["boundary_dir"])
    except BoundaryPackageError as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": exc.code,
                "message": exc.user_message,
            },
            status=exc.status_code,
        )

    if boundary_type not in {"raster", "vector"}:
        return JsonResponse(
            {
                "status": "error",
                "code": "invalid_boundary_type",
                "message": "Boundary type must be raster or vector.",
            },
            status=400,
        )

    if boundary_type == "raster":
        raster_dir = generation.raster_dir
        raster_filepaths = [path for path in raster_dir.glob("**/*") if
                            path.is_file() and path.suffix.lower() == ".tif"]
        for r in raster_filepaths:
            boundary_list.append({"filename": r.name, "size_bytes": r.stat().st_size, "type": "raster"})

    else:
        vector_dir = generation.vector_dir
        vector_filepaths = [
            path
            for path in vector_dir.glob("**/*")
            if path.is_file() and path.suffix.lower() in {".shp", ".gpkg"}
        ]
        for v in vector_filepaths:
            boundary_list.append({"filename": v.name, "size_bytes": v.stat().st_size, "type": "vector"})

    return JsonResponse(boundary_list, safe=False)


def boundaries_upload_page(request):
    """Render the private boundary-upload page."""

    return render(request, 'dashboard/boundaries_upload.html')


def boundaries_upload(request):
    """Validate and atomically activate a private boundary package upload."""

    uploaded_file = request.FILES.get("file")
    if uploaded_file is None:
        return JsonResponse(
            {
                "is_valid": False,
                "code": "missing_boundary_package",
                "message": "A boundary package ZIP file is required.",
            },
            status=400,
        )

    try:
        result = replace_boundary_package(
            uploaded_file,
            CONFIG["boundary_dir"],
            lock_timeout=30,
        )
    except BoundaryPackageError as exc:
        return JsonResponse(
            {
                "is_valid": False,
                "code": exc.code,
                "message": exc.user_message,
            },
            status=exc.status_code,
        )

    return JsonResponse(
        {
            "is_valid": True,
            "message": "The boundary package was activated successfully.",
            "package": {
                "sha256": result.sha256,
                "archive_size": result.archive_size,
                "file_count": result.file_count,
                "uncompressed_size": result.uncompressed_size,
            },
        }
    )



def delivery_delete(request):
    """
    Deletes a delivery from the database and deleted the associated ZIP file from the filesystem.
    """
    try:
        delivery_ids = parse_positive_identifier_list(request.POST.get("ids"))
    except IdentifierListError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    deliveries_by_id = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    if len(deliveries_by_id) != len(delivery_ids):
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_not_found",
                "message": "One or more selected deliveries do not exist.",
            },
            status=404,
        )

    account_access = access_for_request(request)
    if any(
        not account_access.can_manage_user(deliveries_by_id[delivery_id].user_id)
        for delivery_id in delivery_ids
    ):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot delete one or more selected deliveries.",
            },
            status=403,
        )

    active_job = models.Job.objects.filter(
        delivery_id__in=delivery_ids,
        job_status__in=(JOB_WAITING, JOB_RUNNING),
    ).values_list("job_status", flat=True).first()
    if active_job is not None:
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_has_active_job",
                "message": "A selected delivery has a waiting or running QC job.",
            },
            status=409,
        )

    for delivery_id in delivery_ids:
        delivery = deliveries_by_id[delivery_id]
        if delivery.s3_id:
            continue
        try:
            remove_user_delivery_upload(
                media_root=settings.MEDIA_ROOT,
                username=delivery.user.username,
                filename=delivery.filename,
            )
        except DeliveryUploadPathError as exc:
            return JsonResponse(
                {"status": "error", "code": exc.code, "message": exc.message},
                status=exc.status_code,
            )

    models.Delivery.objects.filter(id__in=delivery_ids).update(is_deleted=True)
    return JsonResponse(
        {
            "status": "ok",
            "message": "{:d} deliveries have been deleted.".format(
                len(delivery_ids)
            ),
        }
    )


def job_delete(request):
    """
    Deletes the job from the database and associated files from the filesystem.
    """
    try:
        job_uuids = parse_uuid_identifier_list(request.POST.get("uuids"))
    except IdentifierListError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    jobs = list(
        models.Job.objects.filter(job_uuid__in=job_uuids).select_related(
            "delivery"
        )
    )
    if len(jobs) != len(job_uuids):
        return JsonResponse(
            {
                "status": "error",
                "code": "job_not_found",
                "message": "One or more selected jobs do not exist.",
            },
            status=404,
        )

    account_access = access_for_request(request)
    if any(not account_access.can_manage_user(job.delivery.user_id) for job in jobs):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot delete one or more selected jobs.",
            },
            status=403,
        )
    if any(job.job_status == JOB_RUNNING for job in jobs):
        return JsonResponse(
            {
                "status": "error",
                "code": "job_is_running",
                "message": "A running QC job cannot be deleted.",
            },
            status=409,
        )

    deleted_count, _details = models.Job.objects.filter(
        job_uuid__in=job_uuids
    ).delete()
    return JsonResponse(
        {
            "status": "ok",
            "message": "{:d} jobs deleted successfully.".format(deleted_count),
        }
    )


def submit_delivery_to_eea(request):
    if request.method == "POST":
        try:
            delivery_id = parse_positive_identifier_list(
                request.POST.get("id"),
                maximum_items=1,
            )[0]
        except IdentifierListError as exc:
            return JsonResponse(
                {"status": "error", "code": exc.code, "message": exc.message},
                status=400,
            )

        # Check if delivery with given ID exists.
        try:
            d = models.Delivery.objects.get(id=delivery_id)
        except ObjectDoesNotExist:
            response = JsonResponse({"status": "error",
                                     "message": "Delivery id={0} cannot be found in the database.".format(delivery_id)})
            response.status_code = 404
            return response
        filename = d.filename

        if not access_for_request(request).can_manage_user(d.user_id):
            return JsonResponse(
                {"status": "error", "message": "Delivery belongs to another user."},
                status=403,
            )

        try:
            logger.debug("delivery_submit_eea id=" + str(delivery_id))

            # zip_filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)

            job = d.get_submittable_job()
            if job is None:
                message = "Delivery {:s} cannot be submitted to EEA. Status is not OK.)".format(d.filename)
                response = JsonResponse({"status": "error", "message": message})
                response.status_code = 400
                return response
            submission_date = timezone.now()

            if d.s3:
                submit_job(job.job_uuid, None, CONFIG["submission_dir"], submission_date, is_s3=True)
            else:
                zip_filepath = resolve_user_delivery_upload(
                    d.filename,
                    media_root=settings.MEDIA_ROOT,
                    username=d.user.username,
                )
                submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)


            # submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date)
            d.submit()
            d.submission_date = submission_date
            d.save()
        except DeliveryUploadPathError as exc:
            d.date_submitted = None
            d.save()
            return JsonResponse(
                {
                    "status": "error",
                    "code": exc.code,
                    "message": exc.message,
                },
                status=exc.status_code,
            )
        except Exception:
            d.date_submitted = None
            d.save()
            logger.exception("Failed to submit delivery id=%s.", d.id)
            return JsonResponse(
                {
                    "status": "error",
                    "code": "submission_failed",
                    "message": "The delivery could not be submitted.",
                },
                status=500,
            )

        return JsonResponse({"status":"ok",
                             "message": "Delivery {0} successfully submitted to EEA.".format(filename)})


def submit_deliveries_to_eea_batch(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

    try:
        delivery_ids = parse_positive_identifier_list(request.POST.get("ids"))
    except IdentifierListError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )
    submitted_ids = []
    failed_details = [] # Store reasons for failure
    account_access = access_for_request(request)

    for delivery_id in delivery_ids:
        display_name = "Delivery ID {}".format(delivery_id)
        try:
            d = models.Delivery.objects.get(id=delivery_id)
            display_name = d.filename
            if not account_access.can_manage_user(d.user_id):
                failed_details.append(f"{display_name}: Delivery belongs to another user")
                continue
            
            # Check status logic
            job = d.get_submittable_job()
            if job is None:
                failed_details.append(f"{display_name}: Status not OK")
                continue # Move to the next delivery, don't stop the whole process

            submission_date = timezone.now()

            # Submission execution
            if d.s3:
                submit_job(job.job_uuid, None, CONFIG["submission_dir"], submission_date, is_s3=True)
            else:
                zip_filepath = resolve_user_delivery_upload(
                    d.filename,
                    media_root=settings.MEDIA_ROOT,
                    username=d.user.username,
                )
                submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)

            # Update record
            d.submit()
            d.submission_date = submission_date
            d.save()
            submitted_ids.append(delivery_id)

        except ObjectDoesNotExist:
            failed_details.append(f"ID {delivery_id}: Not found")
        except DeliveryUploadPathError as exc:
            logger.warning(
                "Rejected unsafe submission path for delivery id=%s (%s).",
                delivery_id,
                exc.code,
            )
            failed_details.append(f"{display_name}: Delivery file is unavailable")
        except Exception:
            logger.exception("Failed to submit delivery id=%s.", delivery_id)
            failed_details.append(f"{display_name}: System error")

    # --- Final Response Logic ---
    total_requested = len(delivery_ids)
    total_submitted = len(submitted_ids)

    if total_submitted == 0:
        return JsonResponse({
            "status": "error", 
            "message": "None of the deliveries could be submitted.",
            "details": failed_details
        }, status=400)

    return JsonResponse({
        "status": "ok",
        "message": f"{total_submitted}/{total_requested} deliveries successfully submitted.",
        "failed": failed_details
    })


def api_submit_delivery_to_eea(request):
    try:
        body_json = read_json_object(
            request,
            maximum_bytes=API_JSON_MAX_BODY_BYTES,
        )
        delivery_id = positive_identifier(
            body_json.get("delivery_id"),
            "delivery_id",
        )
    except JsonRequestError as exc:
        return _json_request_error_response(exc)
    except JobRequestError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    try:
        d = models.Delivery.objects.get(id=delivery_id)
    except ObjectDoesNotExist:
        response = JsonResponse({"status": "error",
                                 "message": "Delivery id={0} cannot be found in the database.".format(delivery_id)})
        response.status_code = 404
        return response
    if not request.api_access.can_manage_user(d.user_id):
        return JsonResponse(
            {
                "status": "error",
                "code": "object_permission_denied",
                "message": "The account cannot modify this delivery.",
            },
            status=403,
        )
    try:
        logger.debug("delivery_submit_eea id=" + str(delivery_id))

        job = d.get_submittable_job()
        if job is None:
            message = "Delivery with ID '{:d}' cannot be submitted to EEA. Status is not OK.)".format(d.id)
            response = JsonResponse({"status": "error", "message": message})
            response.status_code = 400
            return response
        submission_date = timezone.now()

        # check if the delivery is from local or S3 storage
        if d.s3:
            submit_job(job.job_uuid, None, CONFIG["submission_dir"], submission_date, is_s3=True)
        else:
            zip_filepath = resolve_user_delivery_upload(
                d.filename,
                media_root=settings.MEDIA_ROOT,
                username=d.user.username,
            )
            submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)
        d.submit()
        d.submission_date = submission_date
        d.save()

    except DeliveryUploadPathError as exc:
        d.date_submitted = None
        d.save()
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    except Exception:
        d.date_submitted = None
        d.save()
        logger.exception(
            "Failed to submit delivery id=%s through the API.",
            d.id,
        )
        return JsonResponse(
            {
                "status": "error",
                "code": "submission_failed",
                "message": "The delivery could not be submitted.",
            },
            status=500,
        )

    return JsonResponse({"status": "ok",
                         "message": "Delivery with ID {:d} successfully submitted to EEA.".format(d.id)})

def get_product_list(request):
    """
    returns a list of all product types that are available for checking.
    :param request:
    :return: list of the product types with items {name, description} in JSON format
    """
    product_infos = get_product_descriptions()
    product_list = [{'name': product_ident, 'description': product_description}
                    for product_ident, product_description in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x['description'])
    return JsonResponse({'product_list': product_list})

def get_product_descriptions_dropdown(request):
    """
    returns a list of product descriptions for the UI filter dropdown based on current user.
    :param request:
    :return: dictionary of the product descriptions
    """
    product_descriptions = sorted(
        models.Delivery.objects.filter(
            is_deleted=False,
            user=request.user,
        )
        .values_list("product_description", flat=True)
        .distinct()
    )
    product_dict = {}
    for item in product_descriptions:
        product_dict[item] = item
    return JsonResponse(product_dict)

def get_product_definition(request, product_ident):
    """
    Shows the json product definition.
    """
    filepath = locate_product_definition(product_ident)
    try:
        return FileResponse(open(str(filepath), "rb"), content_type="application/json")
    except FileNotFoundError:
        raise Http404()

def get_job_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of job steps and their type (system, required, optional)
    """
    job_report = compile_job_form_data(product_ident)
    return JsonResponse({'job_result': job_report})


def get_job_history_json(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

    account_access = access_for_request(request)
    require_delivery_view(account_access, delivery)

    # find all jobs with same filename
    candidate_jobs = models.Job.objects.filter(
        delivery__filename=delivery.filename
    ).select_related("delivery__user__userprofile")
    visible_job_ids = [
        job.pk for job in candidate_jobs if can_view_job(account_access, job)
    ]
    jobs = models.Job.objects.filter(pk__in=visible_job_ids).order_by(
        "-date_created"
    )
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)
    return JsonResponse(serialize_job_history(jobs), safe=False)


def job_history_page(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    account_access = access_for_request(request)
    require_delivery_view(account_access, delivery)
    can_delete_jobs = bool(
        account_access.can_delete
        and account_access.can_manage_user(delivery.user_id)
    )
    return render(
        request,
        "dashboard/job_history.html",
        {
            "delivery": delivery,
            "show_logo": settings.SHOW_LOGO,
            "can_delete_jobs": can_delete_jobs,
        },
    )


def get_result(request, job_uuid):
    """
    Shows the result page with detailed results of the selected job.
    """
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    delivery = job.delivery
    job_report = compile_job_report_data(job_uuid, job.product_ident)

    # if job status is not set in the report then try get status from the DB table (case of TIMEOUT or LOST)
    if job_report.get("status") is None:
        job_report["status"] = job.job_status

    for step in job_report["steps"]:
        # Strip initial qc_tool. from check idents.
        if step["check_ident"].startswith("qc_tool."):
            step["check_ident"] = ".".join(step["check_ident"].split(".")[1:])
        # Inform the result page about presence of a check with 'aborted' status.
        if step["status"] == "aborted":
            job_report["aborted_check"] = step["check_ident"]
    return render(request, "dashboard/result.html", {"job_report":job_report,
                                                     "delivery": delivery,
                                                     "show_logo": settings.SHOW_LOGO,
                                                     "announcement": get_announcement_message()
                                                     })


def get_pdf_report(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    try:
        report_file, report_filename = open_job_report(job_uuid)
    except ArtifactUnavailable:
        raise Http404()
    return FileResponse(
        report_file,
        content_type="application/pdf",
        as_attachment=True,
        filename=report_filename,
    )


def get_job_report(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    job_result = compile_job_report_data(job_uuid, job.product_ident)
    return JsonResponse(job_result, safe=False)


def get_combined_job_log(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    stdout_filepath = compose_job_stdout_filepath(job_uuid)
    joblog_filepath = compose_job_log_filepath(job_uuid)

    stdout_log_text = "Loading stdout log .."
    joblog_log_text = "Loading job log .."
    try:
        stdout_log_text = read_text_artifact(
            stdout_filepath.parent,
            stdout_filepath.name,
        )
    except ArtifactUnavailable:
        stdout_log_text = "stdout log: no data."

    try:
        joblog_log_text = read_text_artifact(
            joblog_filepath.parent,
            joblog_filepath.name,
        )
    except ArtifactUnavailable:
        joblog_log_text = "job log: no data."

    combined_log = "STDOUT LOG:" + "\n" + stdout_log_text + "DETAILED JOB LOG:" + "\n" + joblog_log_text
    return HttpResponse(combined_log, content_type="text/plain")


def download_delivery_file(request, delivery_id):
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    require_delivery_view(access_for_request(request), delivery)

    # File existence check.
    if delivery.is_deleted:
        raise Http404("Uploaded file for delivery id={:d} has been deleted by the user.".format(int(delivery_id)))

    # Downloading the delivery Zip file.
    try:
        delivery_filepath = resolve_user_delivery_upload(
            delivery.filename,
            media_root=settings.MEDIA_ROOT,
            username=delivery.user.username,
        )
        delivery_file = open_regular_artifact(
            delivery_filepath.parent,
            delivery_filepath.name,
        )
    except (ArtifactUnavailable, DeliveryUploadPathError):
        raise Http404()
    return FileResponse(
        delivery_file,
        content_type="application/zip",
        as_attachment=True,
        filename=delivery.filename,
    )


def get_attachment(request, job_uuid, attachment_filename):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)
    try:
        attachment_file = open_job_attachment(job_uuid, attachment_filename)
    except ArtifactUnavailable:
        raise Http404()
    return FileResponse(
        attachment_file,
        as_attachment=True,
        filename=attachment_filename,
    )


def update_job(request, job_uuid):
    job = get_object_or_404(models.Job, job_uuid=job_uuid)
    require_job_view(access_for_request(request), job)

    if job.job_status == JOB_RUNNING:
        time_running = (timezone.now() - job.date_started).total_seconds()
        if time_running > CHECK_RUNNING_JOB_DELAY:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)

    return JsonResponse({"id": job.delivery.id, "last_job_uuid": job.job_uuid, "last_job_status": job.job_status})

def create_job(request):
    try:
        job_request = parse_batch_job_creation_request(request.POST)
    except JobRequestError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=400,
        )

    deliveries = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=job_request.delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    missing_ids = [
        delivery_id
        for delivery_id in job_request.delivery_ids
        if delivery_id not in deliveries
    ]
    if missing_ids:
        return JsonResponse(
            {
                "status": "error",
                "code": "delivery_not_found",
                "message": "One or more selected deliveries do not exist.",
            },
            status=404,
        )

    account_access = access_for_request(request)
    for delivery_id in job_request.delivery_ids:
        if not account_access.can_manage_user(deliveries[delivery_id].user_id):
            raise PermissionDenied(
                "A selected delivery belongs to another user."
            )

    try:
        with transaction.atomic():
            for delivery_id in job_request.delivery_ids:
                delivery = deliveries[delivery_id]
                delivery.create_job(
                    job_request.product_ident,
                    job_request.skip_steps,
                )
                logger.debug(
                    "Delivery %d: job has been submitted.",
                    delivery.id,
                )
    except Exception:
        logger.exception("A QC job batch could not be created.")
        return JsonResponse(
            {
                "status": "error",
                "code": "job_creation_failed",
                "message": "The QC jobs could not be created.",
            },
            status=500,
        )

    num_created = len(job_request.delivery_ids)
    if num_created == 1:
        msg = "QC Job has been set up for execution (product: {:s}).".format(
            job_request.product_ident
        )
    else:
        msg = "{:d} QC Jobs have been set up for execution (product: {:s}).".format(
            num_created,
            job_request.product_ident,
        )

    result = {"num_created": num_created, "status": "OK", "message": msg}
    return JsonResponse(result)

def pull_job(request):
    worker_port = CONFIG.get("worker_port", WORKER_PORT)
    try:
        worker_url = worker_origin_from_remote_address(
            request.META.get("REMOTE_ADDR"),
            worker_port,
        )
    except InvalidWorkerUrl:
        return HttpResponseBadRequest("The worker peer address is invalid.")
    job = models.pull_job(worker_url)
    if job is None:
        response = None
    else:
        response = {"job_uuid": job.job_uuid,
                    "product_ident": job.product_ident,
                    "username": job.delivery.user.username,
                    "filename": job.delivery.filename,
                    "skip_steps": job.skip_steps}
        if job.delivery.s3:
            response.update({
                 "s3_host": job.delivery.s3.host,
                 "s3_access_key": job.delivery.s3.access_key,
                 "s3_secret_key": job.delivery.s3.secret_key,
                 "s3_bucketname": job.delivery.s3.bucketname,
                 "s3_key_prefix": job.delivery.s3.key_prefix
            })
    return JsonResponse(response, safe=False)


def uploaded_delivery_file_exists(filename, user_id):
    """
    Helper function used by resumable_upload.
    :param filename: the uploaded .zip file name.
    :param username: the user id.
    :return: Returns: an error message if delivery with same filename and username already exists in the DB.
    """
    existing_deliveries = models.Delivery.objects.filter(
        filename=filename, user_id=user_id).exclude(is_deleted=True)
    if existing_deliveries.count() > 0:
        logger.info("Upload rejected: file {} already exists for user_id={}".format(filename, user_id))

        file_exists_message = "A file named {} already exists. \
                            If you want to replace the file, please delete if first.".format(filename)
        return file_exists_message


def resumable_upload(request):
    parameters = request.GET if request.method == "GET" else request.POST
    try:
        descriptor = ResumableUploadDescriptor.from_mapping(parameters)

        if request.method == "GET":
            paths = prepare_resumable_paths(
                descriptor,
                media_root=settings.MEDIA_ROOT,
                username=request.user.username,
                create=False,
            )
            if is_chunk_stored(paths.chunk_path):
                return HttpResponse(status=200)
            return HttpResponse(status=404)

        conflict_message = uploaded_delivery_file_exists(
            descriptor.filename,
            request.user.id,
        )
        if conflict_message:
            return JsonResponse(
                {
                    "status": "error",
                    "code": "delivery_exists",
                    "message": conflict_message,
                },
                status=409,
            )

        uploaded_chunk = request.FILES.get("file")
        if uploaded_chunk is None:
            raise ResumableUploadError(
                "missing_upload_chunk",
                "The upload chunk is required.",
            )

        paths = prepare_resumable_paths(
            descriptor,
            media_root=settings.MEDIA_ROOT,
            username=request.user.username,
            create=True,
        )
        store_chunk(
            uploaded_chunk,
            paths.chunk_path,
            expected_bytes=descriptor.current_chunk_size,
        )
        if is_upload_complete(descriptor, paths):
            target_filepath = assemble_chunks(descriptor, paths)
            try:
                product_ident = guess_product_ident(target_filepath)
                product_description = find_product_description(product_ident)
                with transaction.atomic():
                    models.Delivery.objects.create(
                        filename=target_filepath.name,
                        size_bytes=target_filepath.stat().st_size,
                        product_ident=product_ident,
                        product_description=product_description,
                        date_uploaded=timezone.now(),
                        user=request.user,
                        is_deleted=False,
                    )
            except Exception as exc:
                try:
                    remove_published_upload(paths, target_filepath)
                except ResumableUploadError:
                    logger.exception(
                        "Failed to remove an unregistered delivery upload for user_id=%s",
                        request.user.id,
                    )
                raise ResumableUploadError(
                    "delivery_registration_failed",
                    "The uploaded delivery could not be registered.",
                    500,
                ) from exc

        return JsonResponse(
            {"status": "ok", "message": "Chunk uploaded successfully."},
            status=200,
        )
    except ResumableUploadError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    

def refresh_job_statuses():
    # This function is running in a background thread, refreshing statuses of running jobs.
    time.sleep(10)
    while True:
        running_jobs = models.Job.objects.filter(job_status=JOB_RUNNING)
        logger.info("Found {:d} running jobs.".format(len(running_jobs)))
        updated_count = 0
        for job in running_jobs:
            time_running = (timezone.now() - job.date_started).total_seconds()
            if time_running > CHECK_RUNNING_JOB_DELAY:
                job_status = check_running_job(str(job.job_uuid), job.worker_url, CONFIG["worker_alive_timeout"])
                if job_status is not None:
                    if job_status != JOB_RUNNING:
                        job.update_status(job_status)
                        updated_count += 1
        logger.info("refresh_job_statuses: Status of {:d} running jobs has been updated.".format(updated_count))
        time.sleep(int(CONFIG["refresh_job_statuses_background_interval"]))
