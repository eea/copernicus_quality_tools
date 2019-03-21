# -*- coding: utf-8 -*-


import logging
import sys
import shutil
import traceback
from pathlib import Path
from zipfile import ZipFile

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import FileSystemStorage
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
    db_deliveries = models.Delivery.objects.filter(user_id=request.user.id)
    return JsonResponse(list(db_deliveries.values()), safe=False)


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
            existing_deliveries = models.Delivery.objects.filter(filename=myfile, user=request.user)
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

            # Save delivery metadata into the database.
            d = models.Delivery()
            d.filename = saved_filename
            d.filepath = user_upload_path
            d.size_bytes = dst_filepath.stat().st_size
            d.product_ident = product_ident
            d.product_description = product_description
            d.user = request.user
            d.save()
            logger.debug("file info object saved successfully to database.")

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
        num_deleted = 0

        # Job status validation.
        for delivery_id in delivery_ids:
            try:
                int(delivery_id)
            except ValueError:
                return HttpResponseBadRequest("delivery id " + delivery_id + " must be a valid integer id.")

            # Existence validation.
            d = get_object_or_404(models.Delivery, pk=int(delivery_id))

            # User validation.
            if request.user.id != d.user.id:
                return PermissionDenied("User {:s} is not authorized to delete delivery {:d}"
                                        .format(request.user.username, d.id))

            # Job status validation.
            if d.last_job_status == JOB_RUNNING:
                return JsonResponse({"status": "error",
                                     "message": "delivery {:s} cannot be deleted. QC job is currently running."
                                                .format(d.filename)})

        deleted_filenames = []
        for delivery_id in delivery_ids:

            # Input validation.
            try:
                int(delivery_id)
            except ValueError:
                return HttpResponseBadRequest("delivery id " + delivery_id + " must be a valid integer id.")

            # Existence validation.
            d = get_object_or_404(models.Delivery, pk=int(delivery_id))

            # User validation.
            if request.user.id != d.user.id:
                return PermissionDenied("User {:s} is not authorized to delete delivery {:d}"
                                        .format(request.user.username, d.id))

            # Job status validation.
            if d.last_job_status == JOB_RUNNING:
                return JsonResponse({"status": "error",
                                     "message": "delivery {:s} cannot be deleted. QC job is currently running."
                                                .format(d.filename)})

            file_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)
            if file_path.exists():
                file_path.unlink()
            d.delete()
            deleted_filenames.append(file_path.name)
        return JsonResponse({"status":"ok", "message": "{:d} deliveries deleted successfully."
                            .format(len(deleted_filenames))})


@csrf_exempt
def submit_delivery_to_eea(request):
    if request.method == "POST":
        file_id = request.POST.get("id")
        filename = request.POST.get("filename")

        logger.debug("delivery_submit_eea id=" + str(file_id))

        d = models.Delivery.objects.get(id=file_id)
        d.submit()
        d.date_submitted = timezone.now()
        d.save()

        try:
            zip_filepath = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(d.filename)
            submit_job(d.last_job_uuid, zip_filepath, CONFIG["submission_dir"], d.date_submitted)
        except BaseException as e:
            d.date_submitted = None
            d.save()
            logger.error("ERROR submitting delivery to EEA. file {:s}. exception {:s}".format(filename, str(e)))
            raise IOError(e)

        return JsonResponse({"status":"ok",
                             "message": "File {0} successfully submitted to EEA.".format(filename)})

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
    delivery = models.Delivery.objects.get(last_job_uuid=job_uuid)
    job_result = compile_job_report_data(job_uuid, delivery.product_ident)
    return JsonResponse(job_result, safe=False)

@login_required
def get_result(request, job_uuid):
    """
    Shows the result page with detailed results of the selected job.
    """
    delivery = models.Delivery.objects.get(last_job_uuid=job_uuid)
    job_report = compile_job_report_data(job_uuid, delivery.product_ident)
    # strip initial qc_tool. from check idents
    for step in job_report["steps"]:
        if step["check_ident"].startswith("qc_tool."):
            step["check_ident"] = ".".join(step["check_ident"].split(".")[1:])
    return render(request, "dashboard/result.html", job_report)

def get_pdf_report(request, job_uuid):
    filepath = compose_job_report_filepath(job_uuid)
    try:
        return FileResponse(open(str(filepath), "rb"), content_type="application/pdf")
    except FileNotFoundError:
        raise Http404()

@login_required
def get_attachment(request, job_uuid, attachment_filename):
    attachment_filepath = compose_attachment_filepath(job_uuid, attachment_filename)
    if attachment_filepath.suffix == ".csv":
        content = attachment_filepath.read_text()
        response = HttpResponse(content, content_type="text/csv")
    elif attachment_filepath.suffix == ".json":
        content = attachment_filepath.read_text()
        response = HttpResponse(content, content_type="application/json")
    else:
        response = HttpResponse(open(str(attachment_filepath), "rb"), content_type="application/zip")

    response['Content-Disposition'] = 'attachment; filename="{:s}"'.format(attachment_filepath.name)
    return response

@login_required
def update_job(request, delivery_id):
    delivery = models.Delivery.objects.get(id=delivery_id)
    if delivery.last_job_status == JOB_RUNNING:
        job_status = check_running_job(delivery.last_job_uuid, delivery.worker_url)
        if job_status is not None:
            delivery.update_job(job_status)
    return JsonResponse(model_to_dict(delivery))

@csrf_exempt
def create_job(request):
    delivery_ids = request.POST.get("delivery_ids").split(",")
    num_created = 0

    for delivery_id in delivery_ids:
        product_ident = request.POST.get("product_ident")
        skip_steps = request.POST.get("skip_steps")
        if skip_steps == "":
            skip_steps = None

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
    delivery = models.pull_job(worker_url)
    if delivery is None:
        response = None
    else:
        response = {"job_uuid": delivery.last_job_uuid,
                    "username": delivery.user.username,
                    "product_ident": delivery.product_ident,
                    "filename": delivery.filename,
                    "skip_steps": delivery.skip_steps}
    return JsonResponse(response, safe=False)
