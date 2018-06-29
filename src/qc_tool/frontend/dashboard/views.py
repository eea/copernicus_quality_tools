# -*- coding: utf-8 -*-

import json
import os
import time
import zipfile

from datetime import datetime
from math import ceil
from pathlib import Path
from requests import get as requests_get
from requests.exceptions import RequestException
from xml.etree import ElementTree

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

from qc_tool.common import compose_job_status_filepath
from qc_tool.common import compose_wps_status_filepath
from qc_tool.common import get_all_wps_uuids
from qc_tool.common import get_product_descriptions
from qc_tool.common import prepare_empty_job_status

from qc_tool.frontend.dashboard.helpers import parse_status_document
from qc_tool.frontend.dashboard.helpers import get_file_or_dir_size


def files(request):
    """
    Displays the main page with uploaded files and action buttons
    """

    # special case - after successful file upload (this will be changed)
    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        filename = fs.save(myfile.name, myfile)
        return render(request, 'dashboard/files.html', {
            'uploaded_filename': os.path.basename(filename)
        })

    return render(request, 'dashboard/files.html')


def jobs(request):
    """
    Displays the page with history of jobs for a specific file
    """
    return render(request, "dashboard/jobs.html")


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

    # Files are uploaded to a subfolder with the same name as the current username
    user_dir_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username)

    # Unzipping will be moved to WPS
    zip_files = [x for x in user_dir_path.iterdir() if x.is_file() and str(x).lower().endswith(".zip")]


    out_list = []
    for filepath in zip_files:

        # getting uploaded time or last modified time of the file
        file_timestamp = filepath.stat().st_mtime
        uploaded_time = datetime.utcfromtimestamp(file_timestamp).strftime('%Y-%m-%d %H:%M:%S')

        # print out file information and status.
        # TODO: retrieve status from job status documents!
        file_info = {"filename": filepath.name,
                     "filepath": str(filepath),
                     "date_uploaded": uploaded_time,
                     "size_bytes": filepath.stat().st_size,
                     "product_ident": "unknown",
                     "product_description": "Unknown",
                     "qc_status": "Not checked",
                     "submitted": "No"}
        out_list.append(file_info)

    return JsonResponse(out_list, safe=False)


# File upload will be moved to chunked_file_uploads
def file_upload(request):

    # file is uploaded to a directory with the same name as the current username
    user_upload_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username)
    if not user_upload_path.exists():
        user_upload_path.mkdir(parents=True)

    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage(str(user_upload_path))
        fs.save(myfile.name, myfile)
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
    returns a table of details about the product type
    :param request:
    :param product_ident: the name of the product type for example clc_chaYY
    :return: details about the product type including the required and optional checks
    """
    job_status = prepare_empty_job_status(product_ident)
    return JsonResponse({'job_status': job_status})


def get_result(request, job_uuid):
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


def get_jobs(request):
    """
    Returns the list of all QA jobs (both running and completed) in JSON format
    :param request:
    :return:
    """
    job_infos = []
    for job_uuid in get_all_wps_uuids():
        wps_status_filepath = compose_wps_status_filepath(job_uuid)
        wps_status = wps_status_filepath.read_text()
        job_info = parse_status_document(wps_status)
        job_info["uid"] = job_uuid

        job_status_filepath = compose_job_status_filepath(job_uuid)
        if job_status_filepath.exists() and job_info["status"] == "finished":
            job_status = job_status_filepath.read_text()
            job_status = json.loads(job_status)
            overall_status_ok = all((check["status"] in ("ok", "skipped") for check in job_status["checks"]))
            job_info["overall_result"] = ["FAILED", "PASSED"][overall_status_ok]

        job_infos.append(job_info)

    # sort by start_time in descending order
    job_infos = sorted(job_infos, key=lambda ji: ji['start_time'], reverse=True)

    return JsonResponse(job_infos, safe=False)
    # for server-side pagination change code to: return JsonResponse({"total": len(docs_sorted), "rows": docs_sorted})


@csrf_exempt
def run_wps_execute(request):
    """
    Called from the web app - Run the process
    """
    try:

        product_ident = request.POST.get("product_type_name")
        filepath = request.POST.get("filepath")
        optional_check_idents = request.POST.get("optional_check_idents")

        if not product_ident:
            product_ident = request.GET.get("product_type_name")
        if not filepath:
            filepath = request.GET.get("filepath")
        if not optional_check_idents:
            optional_check_idents = request.GET.get("optional_check_idents")

        # call wps execute method
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

        #wps_data_inputs = "&DataInputs=filepath={0};product_ident={1};optional_check_idents={2}".format(filepath, product_ident, optional_check_idents)


        # call the wps and receive response
        r = requests_get(wps_url)
        tree = ElementTree.fromstring(r.text)

        # wait for the response
        if "statusLocation" in tree.attrib:

            # process is started
            result = {"status": "OK",
                      "message": "QC job has started and it is running in the background."}
            js = json.dumps(result)
            return HttpResponse(js, content_type='application/json')
        else:

            # process failed to start
            error_response = {"status": "ERR", "message": "There was an error starting the job. Exception: %s" % r.text}
            js = json.dumps(error_response)
            return HttpResponse(js, content_type='application/json')

    except RequestException as e:  # catch exception in case of wps server not responding
        error_response = {"status": "ERR", "message": "WPS server probably does not respond. Error details: %s" % (e)}
        js = json.dumps(error_response)
        return HttpResponse(js, content_type='application/json')
