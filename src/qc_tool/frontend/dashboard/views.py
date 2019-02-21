# -*- coding: utf-8 -*-

import logging
import json
import sys
import shutil
import traceback

from datetime import datetime
from pathlib import Path
from requests import get as requests_get
from requests.exceptions import RequestException
from xml.etree import ElementTree
from zipfile import ZipFile

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import MultipleObjectsReturned, PermissionDenied, ObjectDoesNotExist
from django.core.files.storage import FileSystemStorage

from django.forms.models import model_to_dict

from django.http import FileResponse, HttpResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from qc_tool.common import CONFIG
from qc_tool.common import compile_job_report
from qc_tool.common import compose_attachment_filepath
from qc_tool.common import compose_job_report_filepath
from qc_tool.common import get_product_descriptions
from qc_tool.common import load_product_definition
from qc_tool.common import load_wps_status

from qc_tool.frontend.dashboard.helpers import find_product_description
from qc_tool.frontend.dashboard.helpers import guess_product_ident
from qc_tool.frontend.dashboard.helpers import submit_job
from qc_tool.frontend.dashboard.models import Delivery


logger = logging.getLogger(__name__)

@login_required
def deliveries(request):
    """
    Displays the main page with uploaded files and action buttons
    """
    return render(request, 'dashboard/deliveries.html', {"submission_enabled": settings.SUBMISSION_ENABLED})


@login_required
def start_job(request, delivery_id):
    """
    Displays a page for starting a new QA job
    :param delivery_id: The ID of the delivery ZIP file.
    """
    delivery = get_object_or_404(Delivery, pk=delivery_id)

    product_infos = get_product_descriptions()
    product_list = [{"product_ident": product_ident, "product_description": product_name}
                    for product_ident, product_name in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x["product_description"])

    # Starting a job for a submitted delivery is not permitted.
    if delivery.date_submitted is not None:
        raise PermissionDenied("Starting a new QC job on submitted delivery is not permitted.")

    context = {"filename": delivery.filename,
               "product_ident": delivery.product_ident,
               "product_list": product_list}
    return render(request, "dashboard/start_job.html", context)


@login_required
def get_deliveries_json(request):
    """
    Returns a list of all deliveries for the current user.
    The deliveries are loaded from the dashboard_deliverys database table.
    The associated ZIP files are stored in <MEDIA_ROOT>/<username>/

    :param request:
    :return: list of deliveries in JSON format
    """
    db_deliveries = Delivery.objects.filter(user_id=request.user.id)
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
            existing_deliveries = Delivery.objects.filter(filename=myfile, user=request.user)
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
            d = Delivery()
            d.filename = saved_filename
            d.filepath = user_upload_path
            d.size_bytes = dst_filepath.stat().st_size
            d.product_ident = product_ident
            d.product_description = product_description
            d.wps_status = None
            d.job_status = "Not checked"
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
        file_id = request.POST.get("id")
        filename = request.POST.get("filename")

        logger.debug("delivery_delete id=" + str(file_id))

        f = Delivery.objects.get(id=file_id)
        file_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username).joinpath(f.filename)
        if file_path.exists():
            file_path.unlink()
        f.delete()
        return JsonResponse({"status":"ok", "message": "File {0} deleted successfully.".format(filename)})


@csrf_exempt
def submit_delivery_to_eea(request):
    if request.method == "POST":
        file_id = request.POST.get("id")
        filename = request.POST.get("filename")

        logger.debug("delivery_submit_eea id=" + str(file_id))

        d = Delivery.objects.get(id=file_id)
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
            #return JsonResponse({"status": "error",
            #                     "message": "ERROR submitting file {:s} to EEA. {:s}".format(filename, str(e))})

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
    product_definition = load_product_definition(product_ident)
    return JsonResponse(product_definition)

@login_required
def get_job_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of job steps and their type (system, required, optional)
    """
    job_report = compile_job_report(product_ident=product_ident)
    return JsonResponse({'job_result': job_report})

def get_job_report(request, job_uuid, product_ident):
    job_result = compile_job_report(job_uuid=job_uuid, product_ident=product_ident)
    return JsonResponse(job_result, safe=False)

@login_required
def get_result(request, job_uuid, product_ident):
    """
    Shows the result page with detailed results of the selected job.
    """
    job_report = compile_job_report(job_uuid=job_uuid, product_ident=product_ident)
    return render(request, "dashboard/result.html", job_report)

def get_pdf_report(request, job_uuid):
    report_filepath = compose_job_report_filepath(job_uuid)
    try:
        return FileResponse(open(str(report_filepath), "rb"), content_type='application/pdf')
    except FileNotFoundError:
        raise Http404()

def get_wps_status_xml(request, job_uuid):
    """
    Shows the WPS status xml document of the selected job.
    """
    wps_status = load_wps_status(job_uuid)
    return HttpResponse(wps_status, content_type="application/xml")

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
    delivery = Delivery.objects.get(id=delivery_id)
    delivery.update_job()
    return JsonResponse(model_to_dict(delivery))

@csrf_exempt
def run_wps_execute(request):
    """
    Called from the UI - forwards the call to WPS and runs the process
    """
    try:
        product_ident = request.POST.get("product_ident")
        filepath = request.POST.get("filepath")
        skip_steps = request.POST.get("skip_steps")

        # The WPS Execute request is formatted using HTTP GET
        wps_data_inputs = ["user_name={:s}".format(request.user.username),
                           "filepath={:s}".format(filepath),
                           "product_ident={:s}".format(product_ident),
                           "skip_steps={:s}".format(skip_steps)]

        wps_params = ["service=WPS",
                      "version=1.0.0",
                      "request=Execute",
                      "identifier=run_checks",
                      "storeExecuteResponse=true",
                      "status=true",
                      "lineage=true",
                      "DataInputs={:s}".format(";".join(wps_data_inputs))]

        wps_url = settings.WPS_URL + "?" + "&".join(wps_params)

        # Receive a response from the WPS.
        logger.info("Calling WPS: {:s}".format(wps_url))
        r = requests_get(wps_url)

        # The WPS server should return a XML response.
        tree = ElementTree.fromstring(r.text)

        # wait for the response and get the uuid
        if "statusLocation" in tree.attrib:

            # Job UUID is parsed from the status location in the WPS response.
            # <wps:response statusLocation="http://<wps_host>/status/<JOB_UUID>.xml">
            status_location_url = str(tree.attrib["statusLocation"])
            job_uuid = (status_location_url.split("/")[-1]).split(".")[0]

            # Update delivery status in the frontend database.
            file_path = Path(settings.MEDIA_ROOT).joinpath(filepath)
            file_name = file_path.name
            d = Delivery.objects.get(user=request.user, filename=file_name)
            d.init_job(product_ident, job_uuid)
            logger.debug("Delivery {:d}: job status created with job_uuid={:s}.".format(d.id, str(job_uuid)))

            # The WPS process has been started asynchronously.
            result = {"status": "OK",
                      "message": "QC job has started and it is running in the background. <br>"
                                 "<i>job uuid: " + job_uuid + "</i>",
                      "job_uuid": job_uuid,
                      "wps_url": wps_url}
            js = json.dumps(result)
            return HttpResponse(js, content_type='application/json')
        else:

            # If the WPS response does not have statusLocation then there is a WPS error.
            error_response = {"status": "ERR", "message": "There was an error starting the job. Exception: %s" % r.text}
            js = json.dumps(error_response)
            return HttpResponse(js, content_type='application/json')

    except RequestException as e:  # catch exception in case of wps server not responding
        error_response = {"status": "ERR", "message": "WPS server probably does not respond. Error details: %s" % (e)}
        js = json.dumps(error_response)
        return HttpResponse(js, content_type='application/json')
