# -*- coding: utf-8 -*-

import json
import os
import time
import zipfile

from datetime import datetime
from pathlib import Path
from requests import get as requests_get
from requests.exceptions import RequestException
from xml.etree import ElementTree

from django.conf import settings
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
    if request.method == 'GET' and 'uploaded_filename' in request.GET:
        return render(request, 'dashboard/files.html', {
            'uploaded_file_url': os.path.join(settings.MEDIA_ROOT, request.GET['uploaded_filename'])
        })

    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        filename = fs.save(myfile.name, myfile)
        return render(request, 'dashboard/files.html', {
            'uploaded_file_path': os.path.join(settings.MEDIA_ROOT, filename)
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
    base_dir = settings.MEDIA_ROOT
    valid_filepaths = []

    # Unzipping will be moved to WPS
    for dirpath, subdirs, files in os.walk(base_dir):
        for filepath in files:
            if filepath.lower().endswith('.tif') or filepath.lower().endswith('gdb.zip') or filepath.lower().endswith('tif.zip'):
                full_path = os.path.join(dirpath, filepath)
                valid_filepaths.append(full_path)
        for subdir in subdirs:
            if subdir.endswith('.gdb'):
                full_path = os.path.join(dirpath, subdir)
                valid_filepaths.append(full_path)

    out_list = []
    for filepath in valid_filepaths:
        file_timestamp = os.path.getmtime(filepath)
        uploaded_time = datetime.utcfromtimestamp(file_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        size_kB = get_file_or_dir_size(filepath) >> 10 # converting bytes to MB
        size_MB = float(size_kB) / 1000.0
        if size_MB < 1:
            size_MB = 1
        else:
            size_MB = round(size_MB)

        file_info = {'filename': os.path.basename(filepath),
                     'filepath': filepath,
                     'date_uploaded': uploaded_time,
                     'size_GB': "{:.3f}".format(float(size_MB) / 1000.0),
                     "product_ident": "unknown",
                     'product_description': "Unknown",
                     "submitted": "No"}
        out_list.append(file_info)

    return JsonResponse(out_list, safe=False)


# File upload will be moved to chunked_file_uploads
def file_upload(request):

    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        fs.save(myfile.name, myfile)

        # if it is a zip file then unzip it
        if myfile.name.endswith('gdb.zip'):
            zip_file_path = os.path.join(settings.MEDIA_ROOT, os.path.basename(myfile.name))

            gdb_dir_path = zip_file_path.replace('gdb.zip','gdb')
            os.makedirs(gdb_dir_path)
            print(gdb_dir_path)

            with zipfile.ZipFile(zip_file_path, 'r') as f:
                files = [n for n in f.namelist() if not n.endswith('/')]
                f.extractall(path=settings.MEDIA_ROOT, members=files)
            os.remove(zip_file_path)

        elif myfile.name.endswith('.tif.zip'):
            zip_file_path = os.path.join(settings.MEDIA_ROOT, os.path.basename(myfile.name))

            raster_dir_path = zip_file_path.replace('.tif.zip','')
            os.makedirs(raster_dir_path)

            with zipfile.ZipFile(zip_file_path, 'r') as f:
                files = [n for n in f.namelist() if not n.endswith('/')]
                f.extractall(path=raster_dir_path, members=files)
            os.remove(zip_file_path)

        return redirect('/files/?uploaded_filename={0}'.format(myfile.name))

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
        context = {
            'product_type_name': job_status["product_ident"],
            'product_type_description': job_status["description"],
            'filepath': job_status["filename"],
            'start_time': job_status["job_start_date"],
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
