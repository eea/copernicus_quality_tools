# -*- coding: utf-8 -*-


import logging
import os
import sys
import shutil
import time
import traceback
from pathlib import Path
from zipfile import ZipFile
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied
from django.core.files.storage import FileSystemStorage
from django.db import connection
from django.forms.models import model_to_dict
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import qc_tool.frontend.dashboard.models as models
from qc_tool.common import auth_worker
from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.common import compose_attachment_filepath
from qc_tool.common import compile_job_form_data
from qc_tool.common import compile_job_report_data
from qc_tool.common import get_job_report_filepath
from qc_tool.common import get_product_descriptions
from qc_tool.common import locate_product_definition
from qc_tool.common import WORKER_PORT
from qc_tool.frontend.dashboard.helpers import find_product_description
from qc_tool.frontend.dashboard.helpers import generate_api_key
from qc_tool.frontend.dashboard.helpers import get_announcement_message
from qc_tool.frontend.dashboard.helpers import guess_product_ident
from qc_tool.frontend.dashboard.helpers import find_s3_delivery
from qc_tool.frontend.dashboard.helpers import get_s3_delivery_size
from qc_tool.frontend.dashboard.helpers import submit_job
from qc_tool.frontend.dashboard.helpers import get_boundary_version

logger = logging.getLogger(__name__)

CHECK_RUNNING_JOB_DELAY = 10

UPLOADED_CHUNK_PROCESSING_DELAY = 1

def check_api_key(request):
    api_key = request.GET.get("apikey")
    user = None
    if not api_key:
        msg = "api key was not provided"
        return user, msg
    try:
        api_user = models.ApiUser.objects.get(api_key=api_key)
        user = api_user.user
    except ObjectDoesNotExist:
        msg = "provided api key does not match any user"
    if user:
        msg = "ok"
    return user, msg


def api_homepage(request):
    return render(request, 'dashboard/swagger-ui.html',
                  {
                    "api_url": CONFIG["api_url"],
                    "schema_url": "openapi-schema"
                  })

def api_openapi_json(request):
    api_url = CONFIG["api_url"]
    openapi_json_path = os.path.join(settings.BASE_DIR, "frontend", "dashboard", "static", "dashboard", "api", "openapi.json")
    with open(openapi_json_path, "r") as f:
        openapi_dict = json.load(f)
        openapi_dict["servers"][0]["url"] = api_url
        return JsonResponse(openapi_dict)

def api_register_delivery(request):
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    # Get request body parameters
    try:
        body = request.body.decode("utf-8")
        body_json = json.loads(body)
    except:
        return JsonResponse({"status": "error", "message":"request body is not valid json"}, status=400)

    target_filepath = Path(body_json.get("uploaded_file"))

    if not target_filepath:
        return JsonResponse({"status": "error", "message":"missing parameter: uploaded_file"}, status=400)
    if not target_filepath.exists():
        return JsonResponse({"status": "error", "message": f"uploaded_file does not exist."}, status=404)
    if not target_filepath.name.endswith(".zip"):
        return JsonResponse({"status": "error", "message": f"uploaded_file does not have .zip extension."}, status=400)
    # Assign product description based on product ident.
    # Typically, the product ident is used as the zip filename prefix.
    product_ident = guess_product_ident(target_filepath)
    logger.debug(product_ident)
    product_description = find_product_description(product_ident)

    # Register the uploaded file as a new delivery in the database.
    d = models.Delivery()
    d.filename = target_filepath.name
    d.filepath = target_filepath.parent
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
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    # Get request body parameters
    try:
        body = request.body.decode("utf-8")
        body_json = json.loads(body)
    except:
        return JsonResponse({"status": "error", "message":"request body is not valid json"}, status=400)

    host = body_json.get("host")
    if not host:
        return JsonResponse({"status": "error", "message":"missing parameter: host"}, status=400)

    access_key = body_json.get("access_key")
    if not access_key:
        return JsonResponse({"status": "error", "message":"missing parameter: access_key"}, status=400)

    secret_key = body_json.get("secret_key")
    if not secret_key:
        return JsonResponse({"status": "error", "message":"missing parameter: secret_key"}, status=400)

    bucketname = body_json.get("bucketname")
    if not bucketname:
        return JsonResponse({"status": "error", "message":"missing parameter: bucketname"}, status=400)

    key_prefix = body_json.get("key_prefix")
    if not key_prefix:
        return JsonResponse({"status": "error", "message":"missing parameter: key_prefix"}, status=400)

    # Try to find delivery files in S3
    delivery_filename = find_s3_delivery(host, access_key, secret_key, bucketname, key_prefix)
    if not delivery_filename["delivery_filename"]:
        return JsonResponse({"status": "error", "message": delivery_filename["message"]}, status=400)

    delivery_filename = delivery_filename["delivery_filename"]

    if not delivery_filename:
        return JsonResponse({"status": "error", "message":"s3-key prefix does not match the delivery unambiguously"}, status=400)

    # Get size of the S3 object
    delivery_size = get_s3_delivery_size(host, access_key, secret_key, bucketname, key_prefix)

    # Assign product description based on product ident.
    # Typically, the product ident should be contained in a user-defined filename pattern.
    product_ident = guess_product_ident(Path(delivery_filename))
    logger.debug(product_ident)
    product_description = find_product_description(product_ident)

    # Register the S3 delivery as a new delivery in the database.
    d = models.Delivery()
    d.filename = Path(delivery_filename).name
    d.filepath = None
    d.size_bytes = delivery_size
    d.product_ident = product_ident
    d.product_description = product_description
    d.date_uploaded = timezone.now()
    d.user = user
    d.is_deleted = False
    s3 = models.S3Info()
    s3.host = host
    s3.access_key = access_key
    s3.secret_key = secret_key
    s3.bucketname = bucketname
    s3.key_prefix = key_prefix
    s3.save()
    d.s3=s3
    d.save()
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
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    # Retrieve query parameters (offset, limit).
    # Offset and limit must be positive numbers.
    try:
        offset = int(request.GET.get("offset", 0))
    except ValueError:
        offset = 0
    try:
        limit = int(request.GET.get("limit", 20))
    except ValueError:
        limit = 20
    if offset < 0:
        offset = 0
    if limit < 0:
        limit = 0

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
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    job_form_data = compile_job_form_data(product_ident)
    response_data = {"status": "ok", "message": f"showing available checks for {product_ident}", "data": job_form_data}
    return JsonResponse(response_data, safe=False)

def api_create_job(request):
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    # Get request body parameters
    try:
        body = request.body.decode("utf-8")
        body_json = json.loads(body)
    except:
        return JsonResponse({"status": "error", "message":"request body is not valid json"}, status=400)
    delivery_id = body_json.get("delivery_id")
    product_ident = body_json.get("product_ident")
    skip_steps = body_json.get("skip_steps", None)

    # Handle case when skip_steps parameter is empty string
    if skip_steps == "":
        skip_steps = None

    # Update delivery status in the frontend database.
    try:
        d = models.Delivery.objects.get(id=int(delivery_id))
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "delivery with id={} not found.".format(delivery_id)}
        return JsonResponse(result, status=404)

    # Check if the delivery belongs to authorized user
    if d.user != user:
        result = {"status": "error", "message": "delivery id={} does not belong to user {}.".format(
            delivery_id, user.username)}
        return JsonResponse(result, status=401)

    job_uuid = d.create_job(product_ident, skip_steps)

    response_data = {"job_uuid": str(job_uuid)}
    result = {"status": "OK", "message": "QC job successfully created", "data": response_data}
    return JsonResponse(result)

def api_job_result(request, job_uuid):
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    try:
        job = models.Job.objects.get(job_uuid=job_uuid)
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "job with uuid={} does not exist.".format(job_uuid)}
        return JsonResponse(result, status=404)

    if (job.delivery.user != user):
        result = {"status": "error", "message": "job with uuid={} does not belong to user {}.".format(
            job_uuid, user.username)}
        return JsonResponse(result, status=401)

    job_report = compile_job_report_data(job_uuid, job.product_ident)
    response_data = {"status": "ok", "message": "job status", "data": job_report}
    return JsonResponse(response_data, safe=False)

def api_job_result_pdf(request, job_uuid):
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    try:
        job = models.Job.objects.get(job_uuid=job_uuid)
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "job with uuid={} does not exist.".format(job_uuid)}
        return JsonResponse(result, status=404)

    if (job.delivery.user != user):
        result = {"status": "error", "message": "job with uuid={} does not belong to user {}.".format(
            job_uuid, user.username)}
        return JsonResponse(result, status=401)

    try:
        filepath = get_job_report_filepath(job_uuid)
    except FileNotFoundError:
        # There is no result.
        return JsonResponse({"status": "error", "message": "pdf report does not exist"}, status=404)
    except:
        return JsonResponse({"status": "error", "message": "pdf report is not available"}, status=404)
    try:
        response_pdf = FileResponse(open(str(filepath), "rb"), content_type="application/pdf", as_attachment=True)
    except FileNotFoundError:
        # There is no report.
        return JsonResponse({"status": "error", "message": "pdf report does not exist"}, status=404)
    return response_pdf


def api_job_history(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    # Check delivery existence
    try:
        delivery = models.Delivery.objects.get(id=int(delivery_id))
    except ObjectDoesNotExist:
        result = {"status": "error", "message": "delivery with id={} not found.".format(delivery_id)}
        return JsonResponse(result, status=404)

    # Check if the delivery belongs to authorized user
    if delivery.user != user:
        result = {"status": "error", "message": "delivery id={} does not belong to user {}.".format(
            delivery_id, user.username)}
        return JsonResponse(result, status=401)

    jobs = models.Job.objects.filter(delivery__filename=delivery.filename, delivery__user=user) \
        .order_by("-date_created")
    # Ensure job status is up-to-date
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)

    # Remove "-" characters from job uuids
    job_list = list(jobs.values())
    for job_info in job_list:
        job_info["job_uuid"] = str(job_info["job_uuid"]).replace("-", "")
    result = {"status": "OK",
              "message": "Job history of delivery id={}".format(delivery_id),
              "data": job_list}
    return JsonResponse(result)


@login_required
def deliveries(request):
    """
    Displays the main page with uploaded files and action buttons
    """

    # ensure current user has a valid api key and generate the key if it does not exist.
    try:
        api_key = request.user.apiuser.api_key
    except ObjectDoesNotExist:
        api_key = generate_api_key()
        api_user = models.ApiUser(user=request.user, api_key=api_key)
        api_user.save()

    update_job_statuses = CONFIG.get("update_job_statuses", True)
    update_job_statuses_interval = CONFIG.get("update_job_statuses_interval", 30000)
    is_test_group = request.user.groups.filter(name='test_group').exists()

    return render(request, 'dashboard/deliveries.html', {"submission_enabled": settings.SUBMISSION_ENABLED,
                                                         "show_logo": settings.SHOW_LOGO,
                                                         "announcement": get_announcement_message(),
                                                         "boundary_version": get_boundary_version(),
                                                         "api_key": api_key,
                                                         "update_job_statuses": update_job_statuses,
                                                         "update_job_statuses_interval": update_job_statuses_interval,
                                                         "is_test_group": is_test_group})


@login_required
def setup_job(request):
    """
    Displays a page for starting a new QA job
    :param delivery_id: The ID of the delivery ZIP file.
    """

    delivery_ids = request.GET.get("deliveries", "").split(",")

    if len(delivery_ids) == 0:
        raise Http404("No delivery IDs have been specified.")

    # input validation
    for delivery_id in delivery_ids:
        try:
            int(delivery_id)
        except ValueError:
            return HttpResponseBadRequest("Deliveries parameter must be comma-separated ID's.")

    product_infos = get_product_descriptions()
    product_list = [{"product_ident": product_ident, "product_description": product_name}
                    for product_ident, product_name in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x["product_description"])

    deliveries = []
    for delivery_id in delivery_ids:
        delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

        # Starting a job for a submitted delivery is not permitted.
        if delivery.date_submitted is not None:
            raise PermissionDenied("Starting a new QC job on submitted delivery is not permitted.")

        # Starting a job for another user's delivery is not permitted unless you are a superuser.
        if not request.user.is_superuser:
            if delivery.user != request.user:
                raise PermissionDenied("Delivery id={:d} belongs to another user.".format(int(delivery_id)))
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
    try:
        filter_dict = json.loads(filter_str)
    except json.JsonDecodeError:
        logger.warning("Unable to decode filter expression " + filter)
        return ""

    for key, val in filter_dict.items():
        filter_column = column_lookup.get(key)
        if not filter_column:
            # ignore any undefined filter columns
            continue
        if key  == "product_description":
            filter_sql += (f" AND {filter_column}='{val}'")
        elif key == "last_job_status":
            if val == "Not checked":
                filter_sql += (f" AND {filter_column} IS NULL")
            else:
                filter_sql += (f" AND {filter_column}='{val}'")
        else:
            filter_sql += (f" AND {filter_column} LIKE '%{val}%'")
    return filter_sql


def query_deliveries(user, offset=0, limit=20, sort="id", order="desc", filter="", search=""):
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
        "last_job_worker_url": "j.worker_url",
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
    if filter:
        filter_sql = parse_filter(filter, column_lookup)

    # searching is done on filename column only.
    search_sql = ""
    if search:
        search_sql += (f" AND filename LIKE '%{search}%'")

    # Assemble SQL queries
    sql = """
        SELECT d.id, d.filename, u.username, d.date_uploaded, d.size_bytes,
        d.product_ident, d.product_description, d.date_submitted, d.is_deleted,
        d.s3_id,
        j.job_uuid AS last_job_uuid,
        j.worker_url AS last_job_worker_url,
        j.date_created, j.date_started, j.job_status as last_job_status
        FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
        ON j.job_uuid = (
          SELECT job_uuid FROM dashboard_job j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC LIMIT 1)
        INNER JOIN auth_user u
        ON d.user_id = u.id
        WHERE d.is_deleted != 1
        """
    sql_total = "SELECT COUNT (id) FROM dashboard_delivery d WHERE d.is_deleted != 1"

    # special case of sql_total query for job status filter
    if "j.job_status" in filter_sql:
        sql_total = """
        SELECT COUNT (id) FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
            ON j.job_uuid = (
            SELECT job_uuid FROM dashboard_job j
            WHERE j.delivery_id = d.id
            ORDER BY j.date_created DESC LIMIT 1)
        WHERE d.is_deleted != 1
        """

    # Filter items by current user (except for superuser)
    if not user.is_superuser:
        sql_total += f" AND d.user_id = {user.id}"
        sql +=  f" AND user_id = {user.id}"

    # Add filter expression and search expressions to sql queries
    sql_total += filter_sql
    sql_total += search_sql
    sql += filter_sql
    sql += search_sql

    # Add sort, offset and limit to sql query (with assigned or default values)
    sql += f" ORDER BY {sort_column} {order} LIMIT {limit} OFFSET {offset};"

    with connection.cursor() as cursor:
        # fetch total rows
        cursor.execute(sql_total)
        total_result = cursor.fetchone()
        total = int(total_result[0])

        # fetch query results
        cursor.execute(sql)

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
        return total, data


@login_required
def get_deliveries_json(request):
    """
    Returns a list of all deliveries for the current user.
    The deliveries are loaded from the dashboard_deliveries database table.
    The associated ZIP files are stored in <MEDIA_ROOT>/<username>/

    :param request:
    :return: list of deliveries with associated job information in JSON format
    """
    offset = int(request.GET.get("offset", 0))
    limit = int(request.GET.get("limit", 100))
    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    filter = request.GET.get("filter", "")
    search = request.GET.get("search", "")

    total, data = query_deliveries(request.user, offset=offset, limit=limit, sort=sort, 
                                   order=order, filter=filter, search=search)

    return JsonResponse({"total": total, "rows": data})


@csrf_exempt
def resumable_upload_page(request):
    """
    Resumable file upload demo.
    """
    return render(request, 'dashboard/resumable_upload.html')


@csrf_exempt
@login_required
def announcement(request):
    """
    Saves or loads an announcement message.
    """
    if request.method == "GET":

        if CONFIG["announcement_path"].is_file():
            announcement_message = CONFIG["announcement_path"].read_text()
        else:
            announcement_message = ""

        return render(request, 'dashboard/announcement.html', {"announcement": announcement_message})
    else:
        try:
            CONFIG["announcement_path"].write_text(request.POST.get("announcement_text"))
            announcement_text = request.POST.get("announcement_text")
            if announcement_text:
                result_message = "Announcement has been successfully updated."
            else:
                result_message = "Announcement has been successfully removed."
            return render(request, 'dashboard/announcement.html',
                          {"announcement": request.POST.get("announcement_text"),
                           "result_message": result_message})
        except BaseException as e:
            return render(request, 'dashboard/announcement.html',
                          {"announcement": request.POST.get("announcement_text"),
                           "error_message": "Error updating announcement."})


@login_required
def boundaries(request):
    """
    Returns a list of all boundary aoi files in the active boundary package in html format.
    """
    return render(request, 'dashboard/boundaries.html', {})


@login_required
def get_boundaries_json(request, boundary_type):
    """
    Returns a list of all boundary aoi files in the active boundary package in json format.

    :param request:
    :return: list of boundary .tif or .shp file infos with name and size in JSON format
    """
    boundary_list = []

    if boundary_type == "raster":
        raster_dir = CONFIG["boundary_dir"].joinpath("raster")
        raster_filepaths = [path for path in raster_dir.glob("**/*") if
                            path.is_file() and path.suffix.lower() == ".tif"]
        for r in raster_filepaths:
            boundary_list.append({"filepath": str(r), "filename": r.name, "size_bytes": r.stat().st_size, "type": "raster"})

    else:
        vector_dir = CONFIG["boundary_dir"].joinpath("vector")
        vector_filepaths = [path for path in vector_dir.glob("**/*") if
                            path.is_file() and path.suffix.lower() == ".shp" or path.suffix.lower() == ".gpkg"]
        for v in vector_filepaths:
            boundary_list.append({"filepath": str(v), "filename": v.name, "size_bytes": v.stat().st_size, "type": "vector"})

    return JsonResponse(boundary_list, safe=False)


@login_required
def boundaries_upload(request):
    """
    Uploading boundary package via web console.
    default location for storing boundary package is CONFIG["boundary_dir"].
    """
    try:
        boundary_upload_path = Path(CONFIG["boundary_dir"])

        if request.method == 'POST' and request.FILES["file"]:

            # retrieve file info from uploaded zip file
            myfile = request.FILES["file"]
            logger.info("Processing uploaded boundary ZIP file: {:s}".format(myfile.name))

            # Check if there is an existing boundary package and boundary ZIP file. If found, delete.
            dst_filepath = boundary_upload_path.joinpath(myfile.name)
            if dst_filepath.exists():
                logger.debug("deleting abandoned zip file {:s}".format(str(dst_filepath)))
                dst_filepath.unlink()

            logger.debug("saving uploaded boundary zip file to {:s}".format(str(dst_filepath)))
            fs = FileSystemStorage(str(boundary_upload_path))
            fs.save(myfile.name, myfile)
            logger.debug("uploaded boundary zip file saved successfully to filesystem.")

            # Delete unzipped boundary files.
            raster_dir = boundary_upload_path.joinpath("raster")
            if raster_dir.exists():
                shutil.rmtree(str(raster_dir))

            vector_dir = boundary_upload_path.joinpath("vector")
            if vector_dir.exists():
                shutil.rmtree(str(vector_dir))

            # Unzip the uploaded boundary package.
            with ZipFile(str(dst_filepath)) as zip_file:
                zip_file.extractall(path=str(boundary_upload_path))

            data = {'is_valid': True,
                    'name': myfile.name,
                    'url': myfile.name}
            return JsonResponse(data)

    except BaseException as e:
        logger.debug("upload exception!")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        msg = traceback.format_exception(exc_type, exc_value, exc_traceback)
        logger.debug(msg)
        data = {'is_valid': False,
                'name': None,
                'url': None,
                'message': msg}

        return JsonResponse(data)

    return render(request, 'dashboard/boundaries_upload.html')



@csrf_exempt
def delivery_delete(request):
    """
    Deletes a delivery from the database and deleted the associated ZIP file from the filesystem.
    """
    if request.method == "POST":
        delivery_ids = request.POST.get("ids").split(",")
        logger.debug("delivery_delete ids={:s}".format(repr(delivery_ids)))

        # Validate deliveries.
        for delivery_id in delivery_ids:

            # Validate delivery id.
            try:
                int(delivery_id)
            except ValueError:
                error_message = "Delivery id {:s} must be an integer.".format(repr(delivery_id))
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 400
                return response

            # Get delivery entity.
            delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

            # Authorize the user.
            if not request.user.is_superuser:
                if request.user.id != delivery.user.id:
                    error_message = "User {:s} is not authorized to delete delivery {:s}.".format(request.user.username, delivery.filename)
                    response = JsonResponse({"status": "error", "message": error_message})
                    response.status_code = 403
                    return response

            # Abort, if the job is in JOB_WAITING or JOB_RUNNING status.
            waiting_count = models.Job.objects.filter(delivery__id=delivery.id).filter(job_status=JOB_WAITING).count()
            if waiting_count > 0:
                error_message = "Delivery {:s} cannot be deleted. QC job is currently waiting.".format(delivery.filename)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 400
                return response
            running_count = models.Job.objects.filter(delivery__id=delivery.id).filter(job_status=JOB_RUNNING).count()
            if running_count > 0:
                error_message = "Delivery {:s} cannot be deleted. QC job is currently running.".format(delivery.filename)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 400
                return response

        # Delete deliveries.
        for delivery_id in delivery_ids:
            # Get delivery entity.
            delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

            # Delete delivery .zip file on the file system.
            filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(delivery.filename)
            if filepath.exists():
                filepath.unlink()

            # The delivery and its jobs are not actually deleted from the database.
            # Only delivery.is_deleted attribute is set to True.
            # This is done in order to preserve the job history.
            delivery.is_deleted = True
            delivery.save()
        return JsonResponse({"status":"ok", "message": "{:d} deliveries have been deleted.".format(len(delivery_ids))})


@csrf_exempt
def job_delete(request):
    """
    Deletes the job from the database and associated files from the filesystem.
    """
    if request.method == "POST":
        uuids = request.POST.get("uuids")

        logger.debug("job_delete uuids={:s}".format(uuids))

        job_uuids = uuids.split(",")
        num_deleted = 0

        # Job status validation.
        for job_uuid in job_uuids:

            # Existence validation.
            job = get_object_or_404(models.Job, pk=str(job_uuid))

            # User validation.
            if not request.user.is_superuser:
                if request.user.id != job.delivery.user.id:
                    return PermissionDenied("User {:s} is not authorized to delete job {:s}"
                                            .format(request.user.username, job_uuid))

            # Job status validation.
            running_jobs = models.Job.objects.filter(job_uuid=str(job_uuid)).filter(job_status=JOB_RUNNING)
            if len(running_jobs) > 0:
                return JsonResponse({"status": "error",
                                     "message": "Job {:s} cannot be deleted. QC job is currently running."
                                                .format(job_uuid)})
        deleted_jobs = []
        for job_uuid in job_uuids:
            models.Job.objects.filter(job_uuid=str(job_uuid)).delete()
            deleted_jobs.append(job_uuid)
        return JsonResponse({"status":"ok", "message": "{:d} jobs deleted successfully."
                            .format(len(deleted_jobs))})


@csrf_exempt
def submit_delivery_to_eea(request):
    if request.method == "POST":
        delivery_id = request.POST.get("id")
        filename = request.POST.get("filename")

        # Check if delivery with given ID exists.
        try:
            d = models.Delivery.objects.get(id=delivery_id)
        except ObjectDoesNotExist:
            response = JsonResponse({"status": "error",
                                     "message": "Delivery id={0} cannot be found in the database.".format(delivery_id)})
            response.status_code = 404
            return response

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
                zip_filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)
                submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)


            # submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date)
            d.submit()
            d.submission_date = submission_date
            d.save()
        except BaseException as e:
            d.date_submitted = None
            d.save()
            error_message = "ERROR submitting delivery to EEA. file {:s}. exception {:s}".format(filename, str(e))
            logger.error(error_message)
            response = JsonResponse({"status": "error", "message": error_message})
            response.status_code = 500
            return response

        return JsonResponse({"status":"ok",
                             "message": "Delivery {0} successfully submitted to EEA.".format(filename)})

def api_submit_delivery_to_eea(request):

    # Verify api key
    user, message = check_api_key(request)
    if not user:
        return JsonResponse({"status": "error", "message": message}, status=403)

    # Get request body parameters
    try:
        body = request.body.decode("utf-8")
        body_json = json.loads(body)
    except:
        return JsonResponse({"status": "error", "message":"request body is not valid json"}, status=400)

    # Check if delivery with given ID exists.
    delivery_id = body_json.get("delivery_id")
    if not delivery_id:
        return JsonResponse({"status": "error", "message": "missing parameter: delivery_id"}, status=400)
    try:
        d = models.Delivery.objects.get(id=delivery_id)
    except ObjectDoesNotExist:
        response = JsonResponse({"status": "error",
                                 "message": "Delivery id={0} cannot be found in the database.".format(delivery_id)})
        response.status_code = 404
        return response
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
            zip_filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)
            submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date, is_s3=False)
        d.submit()
        d.submission_date = submission_date
        d.save()

    except BaseException as e:
        d.date_submitted = None
        d.save()
        error_message = "ERROR submitting delivery to EEA. Delivery ID '{:d}'. exception {:s}".format(d.id, str(e))
        logger.error(error_message)
        response = JsonResponse({"status": "error", "message": error_message})
        response.status_code = 500
        return response

    return JsonResponse({"status": "ok",
                         "message": "Delivery with ID {:d} successfully submitted to EEA.".format(d.id)})

@login_required
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
    if request.user.is_superuser:
        sql = ("SELECT product_description FROM dashboard_delivery WHERE is_deleted != 1 AND user_id={} GROUP BY product_description"
               .format(request.user.id))
    else:
        sql = ("SELECT product_description FROM dashboard_delivery WHERE is_deleted != 1 AND user_id={} GROUP BY product_description"
               .format(request.user.id))
    with connection.cursor() as cursor:
        # fetch query results
        cursor.execute(sql)
        # arrange the results
        rows = cursor.fetchall()
        data = []
        for row in rows:
            data.append(row[0])
    product_descriptions = sorted(data)
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

@login_required
def get_job_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of job steps and their type (system, required, optional)
    """
    job_report = compile_job_form_data(product_ident)
    return JsonResponse({'job_result': job_report})

def get_job_report(request, job_uuid):
    job = models.Job.objects.get(job_uuid=job_uuid)
    job_result = compile_job_report_data(job_uuid, job.product_ident)
    return JsonResponse(job_result, safe=False)

def get_job_history_json(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

    if not request.user.is_superuser:
        if delivery.user != request.user:
            raise PermissionDenied("Delivery id={:d} belongs to another user.".format(int(delivery_id)))

    # find all jobs with same filename
    if request.user.is_superuser:
        # superuser can see all jobs.
        jobs = models.Job.objects.filter(delivery__filename=delivery.filename) \
            .order_by("-date_created")
    else:
        # regular user can only see their own jobs.
        jobs = models.Job.objects.filter(delivery__filename=delivery.filename)\
            .filter(delivery__user=request.user)\
            .order_by("-date_created")
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)
    return JsonResponse(list(jobs.values()), safe=False)

def job_history_page(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    if not request.user.is_superuser:
        if delivery.user != request.user:
            raise PermissionDenied("Delivery id={:d} belongs to another user.".format(int(delivery_id)))
    return render(request, 'dashboard/job_history.html', {"delivery": delivery,
                                                          "show_logo": settings.SHOW_LOGO})
@login_required
def get_result(request, job_uuid):
    """
    Shows the result page with detailed results of the selected job.
    """
    job = models.Job.objects.get(job_uuid=job_uuid)
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
    try:
        filepath = get_job_report_filepath(job_uuid)
    except FileNotFoundError:
        # There is no result.
        raise Http404()
    try:
        response = FileResponse(open(str(filepath), "rb"), content_type="application/pdf", as_attachment=True)
    except FileNotFoundError:
        # There is no report.
        raise Http404()
    return response

@login_required
def download_delivery_file(request, delivery_id):
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))

    # Authorization check.q
    if not request.user.is_superuser:
        if delivery.user != request.user:
            raise PermissionDenied("You are not authorized to view uploaded file for delivery id={:d}."
                                   .format(int(delivery_id)))
    # File existence check.
    if delivery.is_deleted:
        raise Http404("Uploaded file for delivery id={:d} has been deleted by the user.".format(int(delivery_id)))

    # Downloading the delivery Zip file.
    try:
        delivery_filepath = Path(settings.MEDIA_ROOT).joinpath(delivery.user.username, delivery.filename)
        return FileResponse(open(str(delivery_filepath), "rb"), content_type="application/zip", as_attachment=True)
    except FileNotFoundError:
        raise Http404()

@login_required
def get_attachment(request, job_uuid, attachment_filename):
    attachment_filepath = compose_attachment_filepath(job_uuid, attachment_filename)
    return FileResponse(open(str(attachment_filepath), "rb"), as_attachment=True)

@login_required
def update_job(request, job_uuid):
    job = models.Job.objects.get(job_uuid=job_uuid)

    if job.job_status == JOB_RUNNING:
        time_running = (timezone.now() - job.date_started).total_seconds()
        if time_running > CHECK_RUNNING_JOB_DELAY:
            job_status = check_running_job(str(job.job_uuid), job.worker_url,
                                           CONFIG["worker_alive_timeout"])
            if job_status is not None:
                job.update_status(job_status)

    return JsonResponse({"id": job.delivery.id, "last_job_uuid": job.job_uuid, "last_job_status": job.job_status})

@csrf_exempt
def create_job(request):
    delivery_ids = request.POST.get("delivery_ids").split(",")
    product_ident = request.POST.get("product_ident")
    skip_steps = request.POST.get("skip_steps")
    if skip_steps == "":
        skip_steps = None

    num_created = 0

    for delivery_id in delivery_ids:
        # Input validation.
        try:
            int(delivery_id)
        except ValueError:
            return HttpResponseBadRequest("delivery id " + delivery_id + " must be a valid integer id.")

        # Update delivery status in the frontend database.
        d = models.Delivery.objects.get(id=int(delivery_id))
        d.create_job(product_ident, skip_steps)
        num_created += 1
        logger.debug("Delivery {:d}: job has been submitted.".format(d.id))

    if num_created == 1:
        msg = "QC Job has been set up for execution (product: {:s}).".format(product_ident)
    else:
        msg = "{:d} QC Jobs have been set up for execution (product: {:s}).".format(num_created, product_ident)

    result = {"num_created": num_created, "status": "OK", "message": msg}
    return JsonResponse(result)

def pull_job(request):
    try:
        token = request.GET.get("token")
        if not auth_worker(token):
            return HttpResponse(status=401)
    except:
        return HttpResponse(status=400)
    worker_url = "http://{:s}:{:d}/".format(request.META["REMOTE_ADDR"], WORKER_PORT)
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


def get_chunk_name(uploaded_filename, chunk_number):
    return uploaded_filename + "_part_{:03d}".format(chunk_number)

def merge_uploaded_chunks(chunk_paths, target_filepath):
    with open(str(target_filepath), "ab+") as target_file:
        for stored_chunk_filepath in chunk_paths:
            stored_chunk_file = open(str(stored_chunk_filepath), "rb")
            target_file.write(stored_chunk_file.read())
            stored_chunk_file.close()
            stored_chunk_filepath.unlink()
    target_file.close()
    logger.debug("Uploaded file saved to: " + str(target_filepath))


def remove_old_chunks(chunks_dir):
    old_chunks = [chunk for chunk in chunks_dir.iterdir() if chunk.is_file()]
    for old_chunk in old_chunks:
        try:
            old_chunk.unlink()
        except:
            pass


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


@csrf_exempt
def resumable_upload(request):
    if request.method == "GET":
        resumableIdentifier = str(request.GET.get("resumableIdentifier"))
        resumableFilename = str(request.GET.get("resumableFilename"))
        resumableChunkNumber = int(request.GET.get("resumableChunkNumber"))

        if not resumableIdentifier or not resumableFilename or not resumableChunkNumber:
            # Parameters are missing or invalid
            return JsonResponse({"status":"error", "message": "Missing or invalid parameters."}, status=500)

        # path where data should be uploaded to
        user_upload_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username, "uploads")
        if not user_upload_path.exists():
           logger.info("Creating a directory for user uploads: {:s}.".format(str(user_upload_path)))
           user_upload_path.mkdir(parents=True)

        # chunk folder path based on the parameters
        chunks_dir = user_upload_path.joinpath(resumableIdentifier)

        # chunk path based on the parameters
        chunk_file = chunks_dir.joinpath(get_chunk_name(resumableFilename, resumableChunkNumber))
        logger.debug('Getting chunk: %s', chunk_file)

        if chunk_file.is_file():
            # Let resumable.js know this chunk already exists
            return HttpResponse(status=200)
        else:
            # Let resumable.js know this chunk does not exists and needs to be uploaded
            return HttpResponse(status=404)

    if request.method == "POST":
        resumableTotalChunks = int(request.POST.get('resumableTotalChunks'))
        resumableChunkNumber = int(request.POST.get('resumableChunkNumber'))
        resumableFilename = str(request.POST.get('resumableFilename'))
        resumableIdentifier = str(request.POST.get('resumableIdentifier'))


        # Get the chunk data.
        chunk_data = request.FILES.get("file")

        # Make a temp directory for the uploads if needed.
        # The upload directory will be located at INCOMING_DIR/<user>/uploads.
        user_upload_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username, "uploads")
        if not user_upload_path.exists():
            logger.info("Creating a directory for user uploads: {:s}.".format(str(user_upload_path)))
            user_upload_path.mkdir(parents=True, exist_ok=True)

        # Chunk folder path is based on the resumableIdentifier parameter.
        chunks_dir = user_upload_path.joinpath(resumableIdentifier)
        if not chunks_dir.is_dir():
            chunks_dir.mkdir(parents=True, exist_ok=True)

        # If delivery already exists in the DB, return 409 conflict status.
        if resumableChunkNumber == 1:
            conflict_message = uploaded_delivery_file_exists(resumableFilename, request.user.id)
            if conflict_message:
                remove_old_chunks(chunks_dir)
                return HttpResponse(conflict_message, status=409)

        # Simulate delay in chunk processing.
        time.sleep(UPLOADED_CHUNK_PROCESSING_DELAY)

        # Save the chunk data.
        chunk_name = get_chunk_name(resumableFilename, resumableChunkNumber)
        chunk_filepath = chunks_dir.joinpath(chunk_name)

        fs = FileSystemStorage(str(chunk_filepath.parent))
        fs.save(chunk_filepath.name, chunk_data)
        logger.info("Saved chunk: " + chunk_filepath.name)

        # Check if the upload is complete.
        chunk_paths = [chunks_dir.joinpath(get_chunk_name(resumableFilename, x)) for x in
                       range(1, resumableTotalChunks + 1)]
        upload_complete = all([p.is_file() for p in chunk_paths])

        # Combine all the chunks to create the final file.
        if upload_complete:

            # If delivery already exists in the DB, return 409 conflict status.
            conflict_message = uploaded_delivery_file_exists(resumableFilename, request.user.id)
            if conflict_message:
                remove_old_chunks(chunks_dir)
                return HttpResponse(conflict_message, status=409)

            # Uploaded file will be copied to INCOMING_DIR/{USERNAME}/{FILENAME}.
            user_incoming_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username)
            if not user_incoming_path.exists():
                logger.info("Creating a directory for user-incoming files: {:s}.".format(str(user_incoming_path)))
                user_incoming_path.mkdir(parents=True, exist_ok=True)
            target_filepath = user_incoming_path.joinpath(resumableFilename)
            merge_uploaded_chunks(chunk_paths, target_filepath)

            # Assign product description based on product ident.
            # Typically, the product ident is used as the zip filename prefix.
            product_ident = guess_product_ident(target_filepath)
            logger.debug(product_ident)
            product_description = find_product_description(product_ident)

            # Register the uploaded file as a new delivery in the database.
            d = models.Delivery()
            d.filename = target_filepath.name
            d.filepath = user_incoming_path
            d.size_bytes = target_filepath.stat().st_size
            d.product_ident = product_ident
            d.product_description = product_description
            d.date_uploaded = timezone.now()
            d.user = request.user
            d.is_deleted = False
            d.save()
            logger.debug("Delivery object saved successfully to database.")

        return JsonResponse({"status":"ok", "message": "Chunk uploaded successfully."}, status=200)

    else:
        return JsonResponse({"status":"error", "message": "request method must be 'GET' or 'POST'."}, status=500)
    

@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user) # dont logout the user.
            messages.success(request, "Password changed.")
            return redirect("/")
    else:
        form = PasswordChangeForm(request.user)
    data = {
        'form': form
    }
    return render(request, "registration/change_password.html", data)


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
