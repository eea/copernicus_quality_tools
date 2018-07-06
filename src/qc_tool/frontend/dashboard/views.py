# -*- coding: utf-8 -*-

import logging
import json
import os
import time
import threading
import uuid
import zipfile

from datetime import datetime
from math import ceil
from pathlib import Path
from requests import get as requests_get
from requests.exceptions import RequestException
from xml.etree import ElementTree

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import exceptions as django_exceptions
from django.core.files.storage import FileSystemStorage
from django.db import connection

from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

from qc_tool.common import compose_job_status_filepath
from qc_tool.common import compose_wps_status_filepath
from qc_tool.common import get_all_wps_uuids
from qc_tool.common import get_product_descriptions
from qc_tool.common import load_product_definition
from qc_tool.common import prepare_empty_job_status

from qc_tool.frontend.dashboard.helpers import guess_product_ident
from qc_tool.frontend.dashboard.helpers import parse_status_document
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import UploadedFile


logger = logging.getLogger(__name__)
timer_is_running = False

@login_required
def files(request):
    """
    Displays the main page with uploaded files and action buttons
    """

    # special case - after successful file upload (this will be changed)
    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        filename = fs.save(myfile.name, myfile)

        f = UploadedFile(
            filename=Path(filename).name,
            filepath=str(Path(filename)),
            status="Not checked",
            user=request.user,
        )
        f.save()

        return render(request, 'dashboard/files.html', {
            'uploaded_filename': os.path.basename(filename)
        })

    return render(request, 'dashboard/files.html')


def jobs(request, filename):
    """
    Displays the page with history of jobs for a specific file
    """
    return render(request, "dashboard/jobs.html", {"filename": filename})


def start_job(request, filename, product):
    """
    Displays a page for starting a new QA job
    """
    return render(request, "dashboard/start_job.html",{"filename": filename, "product": product})


def get_files_json(request):
    """
    Returns a list of all files that are available for checking.
    The files are loaded from the directory specified in settings.MEDIA_ROOT.

    :param request:
    :return: list of the files in JSON format
    """

    # retrieve file metadata and related jobs from the frontend database
    sql = """SELECT f.id, f.filepath, f.filename,  f.date_uploaded, 
    j.end as last_job_time, j.job_uuid as last_job_uuid, j.status, j.product_ident 
    FROM (dashboard_uploadedfile As f INNER JOIN dashboard_job As j ON f.filename = j.filename) 
    INNER JOIN (SELECT max(end) As lasttime, filename FROM dashboard_job WHERE user_id={0} GROUP BY filename) As mj 
    ON mj.lasttime = j.end AND mj.filename = f.filename 
    UNION
    SELECT id, filepath, filename, date_uploaded, 
    NULL AS last_job_time, NULL AS last_job_uuid, NULL AS status, product_ident 
    FROM dashboard_uploadedfile
    WHERE user_id={0} AND filename NOT IN (SELECT filename FROM dashboard_job WHERE user_id={0})
    """.format(request.user.id)
    logger.debug(sql)

    with connection.cursor() as cur:
        cur.execute(sql)
        columns = [col[0] for col in cur.description]
        db_file_infos = [
            dict(zip(columns, row))
            for row in cur.fetchall()
        ]

    db_valid_files = [f for f in db_file_infos if Path(f["filepath"]).joinpath(f["filename"]).exists()
                      and f["filename"].endswith("zip")]

    matching_files = []
    for f in db_valid_files:
        filepath = Path(f["filepath"]).joinpath(f["filename"])

        # getting product description from lookup table
        product_description = "Unknown"
        product_descriptions = get_product_descriptions()
        if f["product_ident"] in product_descriptions:
            product_description = product_descriptions[f["product_ident"]]

        file_info = {"id": f["id"],
                     "filename": f["filename"],
                     "filepath": f["filepath"],
                     "date_uploaded": f["date_uploaded"].strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                     "size_bytes": filepath.stat().st_size,
                     "product_ident": f["product_ident"],
                     "username": request.user.username,
                     "product_description": product_description,
                     "last_job_uuid": f["last_job_uuid"],
                     "last_job_time": f["last_job_time"],
                     "qc_status": f["status"],
                     "percent": None,
                     "submitted": "No"}
        matching_files.append(file_info)

    return JsonResponse(matching_files, safe=False)


# File upload will be moved to chunked_file_uploads
def file_upload(request):

    # file is uploaded to a directory with the same name as the current username
    user_upload_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username)
    if not user_upload_path.exists():
        user_upload_path.mkdir(parents=True)

    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage(str(user_upload_path))
        saved_filename = fs.save(myfile.name, myfile)

        # also save file info to db
        f = UploadedFile()
        #f.file = myfile
        f.filename = saved_filename
        f.filepath = user_upload_path
        f.product_ident = guess_product_ident(saved_filename)
        f.status = "Not checked"
        f.user = request.user
        f.save()

        #f.product_ident = guess_product_ident(f.file.name)
        #f.save()

        return redirect('/?uploaded_filename={0}'.format(myfile.name))

    return render(request, 'dashboard/file_upload.html')


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


def get_product_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of checks and their type (system, required, optional)
    """
    job_status = prepare_empty_job_status(product_ident)
    return JsonResponse({'job_status': job_status})


def get_product_config(request, product_ident):
    """
    Shows the json product type configuration of the selected product.
    """
    product_config = load_product_definition(product_ident)
    return JsonResponse(product_config)


def get_wps_status_xml(request, job_uuid):
    """
    Shows the WPS status xml document of the selected job.
    """
    wps_status_filepath = compose_wps_status_filepath(job_uuid)
    wps_status = wps_status_filepath.read_text()
    return HttpResponse(wps_status, content_type="application/xml")


def get_result_json(request, job_uuid):
    """
    Shows the JSON status xml document of the selected job.
    """
    job_status_filepath = compose_job_status_filepath(job_uuid)
    job_status = job_status_filepath.read_text()
    job_status = json.loads(job_status)
    return JsonResponse(job_status, safe=False)


def get_result(request, job_uuid):
    """
    Shows the result page with detailed results of the selected job.
    """
    job_status_filepath = compose_job_status_filepath(job_uuid)

    if job_status_filepath.exists():
        job_status = job_status_filepath.read_text()
        job_status = json.loads(job_status)
        job_timestamp = job_status_filepath.stat().st_mtime
        job_end_date = datetime.utcfromtimestamp(job_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        context = {
            'product_type_name': job_status["product_ident"],
            'product_type_description': job_status["description"],
            'filepath': job_status["filename"],
            'start_time': job_status["job_start_date"],
            'end_time': job_end_date,
            'result': {
                'uuid': job_uuid,
                'detail': job_status["checks"]
            }
        }

        # special case of system error: show error information from the WPS xml document
        wps_info = parse_status_document(compose_wps_status_filepath(job_uuid).read_text())
        if wps_info["status"] == "error":
            if "log_info" in wps_info:
                error_check_index = 0
                for check in context["result"]["detail"]:
                    if check["status"] is None:
                        break
                    error_check_index += 1
                context["result"]["detail"][error_check_index]["status"] = "error"
                context["result"]["detail"][error_check_index]["message"] = wps_info["log_info"]

    else:
        context = {
            'product_type_name': None,
            'product_type_description': None,
            'filepath': None,
            'start_time': None,
            'end_time': None,
            'result': {
                'uuid': job_uuid,
                'detail': []
            }
        }

    return render(request, 'dashboard/result.html', context)


def get_jobs(request, filename):
    """
    Returns the list of all QA jobs (both running and completed) in JSON format
    :param request:
    :param filename: filename the name of the uploaded file (same as file hash)
    """
    sql = """
    SELECT j.*, f.filename AS file_filename from dashboard_job j
    INNER JOIN dashboard_uploadedfile f
    ON j.filename = f.filename
    WHERE file_filename = "{:s}"
    AND f.user_id = {:d}
    ORDER BY end DESC
    """.format(filename, request.user.id)
    logger.debug(sql)

    job_infos = []
    with connection.cursor() as cur:
        cur.execute(sql)
        columns = [col[0] for col in cur.description]
        job_infos = [
            dict(zip(columns, row))
            for row in cur.fetchall()
        ]

        # optional check idents: did the user intend to run a full set of checks for the product?
        for job_info in job_infos:
            product_ident = job_info["product_ident"]
            product_def = load_product_definition(product_ident)
            all_checks = product_def["checks"]
            available_optional_checks = [check for check in all_checks if check["required"] == False]

            selected_optional_checks = available_optional_checks
            job_status_filepath = compose_job_status_filepath(job_info["job_uuid"])
            if job_status_filepath.exists():
                job_status = job_status_filepath.read_text()
                job_status = json.loads(job_status)
                if "optional_check_idents" in job_status:
                    selected_optional_checks = job_status["optional_check_idents"]

            if len(selected_optional_checks) == len(available_optional_checks):
                job_info["all_checks_selected"] = True
            else:
                job_info["all_checks_selected"] = False

            job_info["start"] = str(job_info["start"]).replace(" ", "T") + "Z"
            if job_info["end"] is not None:
                job_info["end"] = str(job_info["end"]).replace(" ", "T") + "Z"

        return JsonResponse(job_infos, safe=False)




def save_job_info(job_uuid, user, product_ident, filename):
    """
    Saving a job info to database based on the job's uuid
    :param job_uuid:
    :return:
    """
    try:
        job = Job.objects.get(job_uuid=job_uuid)
    except Job.DoesNotExist:
        job = Job(job_uuid=job_uuid)

    # get job info from status document (assuming document exists)
    wps_status_filepath = compose_wps_status_filepath(job_uuid)
    wps_status = wps_status_filepath.read_text()
    wps_doc = parse_status_document(wps_status)

    if user is not None:
        job.user = user

    # (1) Exception in job status document - run has stopped
    if wps_doc["status"] == "error":
        job.status = "error"

    job.end = wps_doc["end_time"]

    job_status_filepath = compose_job_status_filepath(job_uuid)
    job_info = {"status": None}
    if job_status_filepath.exists():
        job_info = job_status_filepath.read_text()
        job_info = json.loads(job_info)

        #job_filename = job_info["filename"]
        #job.filename = job_filename

        job.start = job_info["job_start_date"]

        job.product_ident = job_info["product_ident"]

        if wps_doc["status"] == "error":
            job.status = "error"
        elif wps_doc["status"] == "accepted":
            job.status = "accepted"
        elif wps_doc["status"] == "started":
            job.status = "started"
        elif any((check["status"] in ("failed", "aborted") for check in job_info["checks"])):
            job.status = "failed"
        elif any(("status" not in check for check in job_info["checks"])):
            job.status = "partial"
        elif any((check["status"] is None or check["status"] == "skipped" for check in job_info["checks"])):
            job.status = "partial"
        elif all((check["status"] == "ok" for check in job_info["checks"])):
            job.status = "ok"
        else:
            job.status = "unknown"

    else:
        job.start = datetime.fromtimestamp(wps_status_filepath.stat().st_mtime)
        job.status = wps_doc["status"]


        #if filename is not None:
        #    job_filepath = Path(settings.MEDIA_ROOT, user.username, filename)
        #    job.filename = job_filepath.name
        if product_ident is not None:
            job.product_ident = product_ident

    # retrieve the file info from the database

    file_info = UploadedFile.objects.get(filename=filename, user=user)
    job.file = file_info

    #save job info to database
    job.save()

    #return JsonResponse()
    job_info["status"] = job.status
    return {"job_status": job.status, "wps_doc_status": wps_doc["status"], "job_info": job_info}


@csrf_exempt
def save_job(request):
    user = request.user
    filename = request.GET.get("filename")
    product_ident = request.GET.get("product_ident")
    job_uuid = request.GET.get("job_uuid")
    out = save_job_info(job_uuid, user, product_ident, filename)
    return JsonResponse(out, safe=False)



@csrf_exempt
def run_wps_execute(request):
    """
    Called from the UI - forwards the call to WPS and runs the process
    """
    try:
        product_ident = request.POST.get("product_type_name")
        filepath = request.POST.get("filepath")
        optional_check_idents = request.POST.get("optional_check_idents")

        #if optional_check_idents == "" or optional_check_idents is None:
        #    wps_data_inputs = ["filepath={:s}".format(filepath),
        #                       "product_ident={:s}".format(product_ident)]
        #else:
        wps_data_inputs = ["filepath={:s}".format(filepath),
                           "product_ident={:s}".format(product_ident),
                           "optional_check_idents={:s}".format(optional_check_idents)]

        wps_params = ["service=WPS",
                      "version=1.0.0",
                      "request=Execute",
                      "identifier=run_checks",
                      "storeExecuteResponse=true",
                      "status=true",
                      "lineage=true",
                      "DataInputs={:s}".format(";".join(wps_data_inputs))]

        wps_url = settings.WPS_URL + "?" + "&".join(wps_params)

        # call the wps and receive response
        r = requests_get(wps_url)
        tree = ElementTree.fromstring(r.text)

        #return HttpResponse(r.text, content_type='application/xml')

        # wait for the response
        if "statusLocation" in tree.attrib:

            status_location_url = str(tree.attrib["statusLocation"])
            job_uuid = (status_location_url.split("/")[-1]).split(".")[0]

            # save job info to database cache
            filename = filepath.split("/")[-1]

            logger.debug("run_wps_execute save_job_info started!")
            save_job_info(job_uuid, request.user, product_ident, filename)
            logger.debug("run_wps_execute save_job_info finished!")

            # process is started
            result = {"status": "OK",
                      "message": "QC job has started and it is running in the background. <br><i>job uuid: " + job_uuid + "</i>",
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


def check_processes():
    # runs the timer every 10 seconds
    time.sleep(10)
    counter = 0
    while True:
        time.sleep(10)
        counter += 1

        db_jobs = Job.objects.filter(status__in=["accepted", "started"])
        n_updates = len(list(db_jobs))
        for db_job in db_jobs:
            save_job_info(db_job.job_uuid, None, None, None)

        msg = "Running the timer: {:d} .....{:d} jobs updated.".format(counter, n_updates)
        logger.info(msg)


def startup():

    print ("STARTUP !!!!!")

    t = threading.Thread(target=check_processes)
    t.setDaemon(True)
    t.start()


