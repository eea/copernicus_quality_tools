# -*- coding: utf-8 -*-


import logging
import sys
import shutil
import traceback
from pathlib import Path
from zipfile import ZipFile

from django.conf import settings
from django.contrib.auth.decorators import login_required
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
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import qc_tool.frontend.dashboard.models as models
from qc_tool.common import auth_worker
from qc_tool.common import check_running_job
from qc_tool.common import CONFIG
from qc_tool.common import JOB_RUNNING
from qc_tool.common import compose_attachment_filepath
from qc_tool.common import compile_job_form_data
from qc_tool.common import compile_job_report_data
from qc_tool.common import compose_job_report_filepath
from qc_tool.common import get_product_descriptions
from qc_tool.common import locate_product_definition
from qc_tool.common import WORKER_PORT
from qc_tool.frontend.dashboard.helpers import find_product_description
from qc_tool.frontend.dashboard.helpers import guess_product_ident
from qc_tool.frontend.dashboard.helpers import submit_job


logger = logging.getLogger(__name__)

CHECK_RUNNING_JOB_DELAY = 10


@login_required
def deliveries(request):
    """
    Displays the main page with uploaded files and action buttons
    """
    return render(request, 'dashboard/deliveries.html', {"submission_enabled": settings.SUBMISSION_ENABLED,
                                                         "show_logo": settings.SHOW_LOGO})


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

        # Starting a job for another user's delivery is not permitted.
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
               "show_logo": settings.SHOW_LOGO}
    return render(request, "dashboard/setup_job.html", context)


@login_required
def get_deliveries_json(request):
    """
    Returns a list of all deliveries for the current user.
    The deliveries are loaded from the dashboard_deliverys database table.
    The associated ZIP files are stored in <MEDIA_ROOT>/<username>/

    :param request:
    :return: list of deliveries in JSON format
    """
    with connection.cursor() as cursor:
        sql = """
        SELECT d.id, d.filename, u.username, d.date_uploaded, d.size_bytes,
        d.product_ident, d.product_description, d.date_submitted,
        j.job_uuid AS last_job_uuid,
        j.date_created, j.date_started, j.job_status as last_job_status
        FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
        ON j.job_uuid = (
          SELECT job_uuid FROM dashboard_job j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC LIMIT 1)
        INNER JOIN auth_user u
        ON d.user_id = u.id
        WHERE d.user_id = %s AND d.is_deleted != 1
          """
        cursor.execute(sql, (request.user.id,))
        header = [i[0] for i in cursor.description]
        rows = cursor.fetchall()
        data = []
        for row in rows:
            data.append(dict(zip(header, row)))

        return JsonResponse(data, safe=False)


@login_required
def file_upload(request):
    """
    Processing file uploads.
    """
    # Each ZIP file is uploaded to <MEDIA_ROOT>/<username>/
    try:
        user_upload_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username)
        if not user_upload_path.exists():
            logger.info("Creating a directory for user-uploaded files: {:s}.".format(str(user_upload_path)))
            user_upload_path.mkdir(parents=True)

        if request.method == 'POST' and request.FILES["file"]:

            # retrieve file info from uploaded zip file
            myfile = request.FILES["file"]
            logger.info("Processing uploaded ZIP file: {:s}".format(myfile.name))

            # Show error if a ZIP delivery with the same name uploaded by the same user already exists in the DB.
            existing_deliveries = models.Delivery.objects.filter(filename=myfile, user=request.user).exclude(is_deleted=True)
            if existing_deliveries.count() > 0:
                logger.info("Upload rejected: file {:s} already exists for user {:s}".format(myfile.name,
                                                                                             request.user.username))
                data = {'is_valid': False,
                        'name': myfile.name,
                        'url': myfile.name,
                        'message': "A file named {0} already exists. "
                                   "If you want to replace the file, please delete if first.".format(myfile)}
                return JsonResponse(data)

            # Check if there is an abandoned ZIP file with the same name in the filesystem but not in the DB.
            # if found, delete.
            dst_filepath = user_upload_path.joinpath(myfile.name)
            if dst_filepath.exists():
                logger.debug("deleting abandoned zip file {:s}".format(str(dst_filepath)))
                dst_filepath.unlink()

            logger.debug("saving uploaded file to {:s}".format(str(dst_filepath)))
            fs = FileSystemStorage(str(user_upload_path))
            saved_filename = fs.save(myfile.name, myfile)
            logger.debug("uploaded file saved successfully to filesystem.")

            # Assign product description based on product ident.
            product_ident = guess_product_ident(Path(user_upload_path).joinpath(myfile.name))
            logger.debug(product_ident)
            product_description = find_product_description(product_ident)

            # Create a new delivery in the database.
            d = models.Delivery()
            d.filename = saved_filename
            d.filepath = user_upload_path
            d.size_bytes = dst_filepath.stat().st_size
            d.product_ident = product_ident
            d.product_description = product_description
            d.date_uploaded = timezone.now()
            d.user = request.user
            d.is_deleted = False
            d.save()
            logger.debug("Delivery object saved successfully to database.")

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

    return render(request, 'dashboard/file_upload.html')




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
                            path.is_file() and path.suffix.lower() == ".shp"]
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
        delivery_ids = request.POST.get("ids")

        logger.debug("delivery_delete ids={:s}".format(delivery_ids))

        delivery_ids = request.POST.get("ids").split(",")

        # Job status validation.
        for delivery_id in delivery_ids:

            # Input validation.
            try:
                int(delivery_id)
            except ValueError:
                error_message = "delivery id {0} must be a valid integer id.".format(delivery_id)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 400
                return response

            # Existence validation.
            d = get_object_or_404(models.Delivery, pk=int(delivery_id))

            # User validation.
            if request.user.id != d.user.id:
                error_message = "User {:s} is not authorized to delete delivery {:d}"
                error_message = error_message.format(request.user.username, d.filename)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 403
                return response

            # Job status validation.
            running_jobs = models.Job.objects.filter(delivery__id=d.id).filter(job_status=JOB_RUNNING)
            if len(running_jobs) > 0:
                error_message = "delivery {:s} cannot be deleted. QC job is currently running.".format(d.filename)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 400
                return response

        deleted_filenames = []
        for delivery_id in delivery_ids:

            # Existence validation again.
            d = get_object_or_404(models.Delivery, pk=int(delivery_id))

            # User validation again.
            if request.user.id != d.user.id:
                error_message = "User {:s} is not authorized to delete delivery {:d}"
                error_message = error_message.format(request.user.username, d.filename)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 403
                return response

            # Job status validation.
            running_jobs = models.Job.objects.filter(delivery__id=d.id).filter(job_status=JOB_RUNNING)
            if len(running_jobs) > 0:
                error_message = "delivery {:s} cannot be deleted. QC job is currently running.".format(d.filename)
                response = JsonResponse({"status": "error", "message": error_message})
                response.status_code = 400
                return response

            # Deleting delivery .zip file on the file system.
            file_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)
            if file_path.exists():
                file_path.unlink()

            # The associated row is not deleted from the database table but its attribute is_deleted is set to True
            # This is done in order to preserve the job history.
            d.is_deleted = True
            d.save()
            deleted_filenames.append(file_path.name)
        return JsonResponse({"status":"ok", "message": "{:d} deliveries deleted successfully."
                            .format(len(deleted_filenames))})


@csrf_exempt
def job_delete(request):
    """
    Deletes a job from the database and deleted the associated files from the filesystem.
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

            zip_filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)

            job = d.get_submittable_job()
            if job is None:
                message = "Delivery {:s} cannot be submitted to EEA. Status is not OK.)".format(d.filename)
                response = JsonResponse({"status": "error", "message": message})
                response.status_code = 400
                return response
            submission_date = timezone.now()
            submit_job(job.job_uuid, zip_filepath, CONFIG["submission_dir"], submission_date)
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

    if delivery.user != request.user:
        raise PermissionDenied("Delivery id={:d} belongs to another user.".format(int(delivery_id)))

    # find all jobs with same filename and user as this delivery
    jobs = models.Job.objects.filter(delivery__filename=delivery.filename)\
        .filter(delivery__user=request.user)\
        .order_by("-date_created")
    for job in jobs:
        if job.job_status == JOB_RUNNING:
            job_status = check_running_job(str(job.job_uuid), job.worker_url)
            if job_status is not None:
                job.update_status(job_status)
    return JsonResponse(list(jobs.values()), safe=False)

def job_history_page(request, delivery_id):
    """
    Shows the history of all jobs for a specific delivery in .json format.
    """
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
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
    # strip initial qc_tool. from check idents
    for step in job_report["steps"]:
        if step["check_ident"].startswith("qc_tool."):
            step["check_ident"] = ".".join(step["check_ident"].split(".")[1:])
    return render(request, "dashboard/result.html", {"job_report":job_report,
                                                     "delivery_id": delivery.id,
                                                     "show_logo": settings.SHOW_LOGO})

def get_pdf_report(request, job_uuid):
    filepath = compose_job_report_filepath(job_uuid)
    try:
        return FileResponse(open(str(filepath), "rb"), content_type="application/pdf")
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
            job_status = check_running_job(str(job.job_uuid), job.worker_url)
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
    return JsonResponse(response, safe=False)
