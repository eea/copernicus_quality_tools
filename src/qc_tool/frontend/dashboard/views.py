# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
import time
import zipfile

from pathlib import Path
from requests import get
from requests.exceptions import RequestException
from xml.etree import ElementTree

from django.conf import settings
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import FileSystemStorage

from django.shortcuts import render
from django.shortcuts import redirect

from .helpers import parse_status_document
from .helpers import get_file_or_dir_size


def index(request):

    return render(request, 'dashboard/homepage.html', {'show_button': True})


def new_job(request):
    """
    Displays a page for starting a new QA job
    """
    return render(request, 'dashboard/new_job.html')


def get_files_json(request):
    """
    Returns a list of all files that are available for checking.
    The files are loaded from the directory specified in settings.INCOMING_DIR.

    :param request:
    :return: list of the files in JSON format
    """
    base_dir = settings.INCOMING_DIR
    valid_filepaths = []

    for dirpath, subdirs, files in os.walk(base_dir):
        for filepath in files:
            if filepath.lower().endswith('.tif') or filepath.lower().endswith('gdb.zip'):
                full_path = os.path.join(dirpath, filepath)
                valid_filepaths.append(full_path)
        for subdir in subdirs:
            if subdir.endswith('.gdb'):
                full_path = os.path.join(dirpath, subdir)
                valid_filepaths.append(full_path)

    out_list = []
    for filepath in valid_filepaths:
        uploaded_time = time.ctime(os.path.getmtime(filepath))
        size_MB = get_file_or_dir_size(filepath) >> 10 # converting bytes to MB
        file_info = {'filename': os.path.basename(filepath),
                     'filepath': filepath,
                     'time': uploaded_time,
                     'size_MB': float(size_MB) / 1000.0 }
        out_list.append(file_info)

    return JsonResponse(out_list, safe=False)


def get_files(request):

    if request.method == 'GET' and 'uploaded_filename' in request.GET:
        return render(request, 'dashboard/files.html', {
            'uploaded_file_url': os.path.join(settings.INCOMING_DIR, request.GET['uploaded_filename'])
        })

    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        filename = fs.save(myfile.name, myfile)
        return render(request, 'dashboard/files.html', {
            'uploaded_file_path': os.path.join(settings.INCOMING_DIR, filename)
        })

    return render(request, 'dashboard/files.html')


def file_upload(request):

    if request.method == 'POST' and request.FILES['myfile']:
        myfile = request.FILES['myfile']
        fs = FileSystemStorage()
        fs.save(myfile.name, myfile)

        # if it is a zip file then unzip it
        if myfile.name.endswith('gdb.zip'):
            zip_file_path = os.path.join(settings.INCOMING_DIR, os.path.basename(myfile.name))

            gdb_dir_path = zip_file_path.replace('gdb.zip','gdb')
            os.makedirs(gdb_dir_path)
            print(gdb_dir_path)

            with zipfile.ZipFile(zip_file_path, 'r') as f:
                files = [n for n in f.namelist() if not n.endswith('/')]
                f.extractall(path=settings.INCOMING_DIR, members=files)
            os.remove(zip_file_path)

        elif myfile.name.endswith('.tif.zip'):
            zip_file_path = os.path.join(settings.INCOMING_DIR, os.path.basename(myfile.name))

            raster_dir_path = zip_file_path.replace('.tif.zip','')
            os.makedirs(raster_dir_path)

            with zipfile.ZipFile(zip_file_path, 'r') as f:
                files = [n for n in f.namelist() if not n.endswith('/')]
                f.extractall(path=raster_dir_path, members=files)
            os.remove(zip_file_path)

        return redirect('/files/?uploaded_filename={0}'.format(myfile.name))

    return render(request, 'dashboard/file_upload.html')


def get_product_types(request):
    """
    returns a list of all product types that are available for checking.
    The files are loaded from the directory specified in settings.PRODUCT_TYPES_DIR
    :param request:
    :return: list of the product types with items {name, description} in JSON format
    """

    wps_host = settings.WPS_HOST
    product_types_url = wps_host + "/product_types"
    resp = get(url=product_types_url)
    product_types_dict = resp.json()
    product_types_list = []
    for key, val in product_types_dict.items():
        product_types_list.append({'name': key, 'description': val['description']})

    product_types_sorted = sorted(product_types_list, key=lambda x: x['description'])
    return JsonResponse({'product_types': product_types_sorted})


def get_product_type_details(request, product_type_name):
    """
    returns a table of details about the product type
    :param request:
    :param product_type: the name of the product type for example clc_chaYY
    :return: details about the product type including the required and optional checks
    """
    product_types_url = settings.WPS_HOST + "/product_types"
    resp = get(url=product_types_url)
    product_types = resp.json()
    product_type_info = product_types[product_type_name]

    # also add check descriptions to product type info
    checks_url = settings.WPS_HOST + "/check_functions"
    resp = get(url=checks_url)
    check_functions = resp.json()
    for index in range(0, len(product_type_info['checks'])):
        ident = product_type_info['checks'][index]['check_ident']
        product_type_info['checks'][index]['description'] = check_functions[ident]
        # need better display of parameters! (make it shorter...)

    return JsonResponse({'product_type': product_type_info})


def get_status_document(request, result_uuid):
    status_doc_url = settings.WPS_HOST + '/output/' + result_uuid + '.xml'
    resp = get(status_doc_url)
    return HttpResponse(resp.content, content_type="application/xml")

def get_result(request, result_uuid):

    # fetch the result status document
    status_doc_url = settings.WPS_HOST + '/output/' + result_uuid + '.xml'
    status_doc = parse_status_document(status_doc_url)
    result_detail = status_doc['result']

    print(result_detail)
    result_list = []
    for id, val in result_detail.items():
        result_list.append({'check_ident': id, 'status': val['status'], 'message': val.get('message')})

    # ensure ordering of the checks based on product type spec. also keep skipped checks
    if 'product_type_name' in status_doc and not status_doc['product_type_name'] is None:

        product_type_name = status_doc['product_type_name']

        # get check descriptions
        checks_url = settings.WPS_HOST + "/check_functions"
        resp = get(url=checks_url)
        check_functions = resp.json()

        product_types_url = settings.WPS_HOST + "/product_types"
        resp = get(url=product_types_url)
        product_types = resp.json()
        product_type_info = product_types[product_type_name]

        checks = product_type_info['checks']
        check_list = []
        for check in checks:
            ident = check['check_ident']
            desc = check_functions[ident]
            check_list.append({'check_ident': ident, 'check_description': desc})

        # sort by the product type order and check_ident
        result_list_sorted = []
        for check in check_list:
            check_ident = check['check_ident']
            if check_ident in result_detail:
                if 'message' in result_detail[check_ident]:
                    check_message = result_detail[check_ident]['message']
                else:
                    check_message = ' '

                result_list_sorted.append({"check_ident": check["check_ident"],
                                           "description": check["check_description"],
                                           "status": result_detail[check_ident]["status"],
                                           "message": check_message})
            else:
                result_list_sorted.append({"check_ident": check["check_ident"],
                                           "description": check["check_description"],
                                           "status": "skipped",
                                           "message": ""})

    else:
        # if product_type is not available then sort by alphabetical order
        product_type_name = 'current_product'
        filepath = 'current_filepath'

        result_list_sorted = sorted(result_list, key=lambda x: x['check_ident'])

    status_doc_basename = os.path.basename(status_doc_url)
    status_doc_url2 = "/status_document/{:s}/".format(status_doc_basename.replace(".xml", ""))

    context = {
        'product_type_name': product_type_name,
        'product_type_description': None,
        'filepath': status_doc['filepath'],
        'start_time': status_doc['start_time'],
        'status_document_url': status_doc_url2,
        'result': {
            'uuid': result_uuid,
            'detail': result_list_sorted
        }
    }
    return render(request, 'dashboard/result.html', context)


def get_jobs(request):
    """
    Returns the list of all QA jobs (both running and completed) in JSON format
    :param request:
    :return:
    """

    # first, retrieve the URL's
    status_docs_api = settings.WPS_HOST + "/status_document_urls"
    resp = get(url=status_docs_api)
    status_doc_urls = resp.json()

    # for each status document, retrieve the info:
    docs = []
    for doc_url in status_doc_urls:
        doc_url2 = "{:s}/output/{:s}".format(settings.WPS_HOST, os.path.basename(doc_url))
        doc = parse_status_document(doc_url2)

        if not doc is None:
            docs.append(doc)

    # sort by start_time in descending order
    docs_sorted = sorted(docs, key=lambda d: d['start_time'], reverse=True)

    return JsonResponse(docs_sorted, safe=False)
    # for server-side pagination change code to: return JsonResponse({"total": len(docs_sorted), "rows": docs_sorted})


@csrf_exempt
def run_wps_execute(request):
    """
    Called from the web app - Run the process
    """
    try:

        product_type_name = request.POST.get("product_type_name")
        filepath = request.POST.get("filepath")
        optional_check_idents = request.POST.get("optional_check_idents")

        if not product_type_name:
            product_type_name = request.GET.get("product_type_name")
        if not filepath:
            filepath = request.GET.get("filepath")
        if not optional_check_idents:
            optional_check_idents = request.GET.get("optional_check_idents")

        # call wps execute method
        wps_base_url = settings.WPS_URL
        wps_base = wps_base_url + "?service=WPS&version=1.0.0&request=Execute&identifier=run_checks&storeExecuteResponse=true&status=true&lineage=true&DataInputs="
        data_inputs = "filepath={0};product_type_name={1};optional_check_idents={2}".format(filepath, product_type_name, optional_check_idents)

        wps_url = wps_base + data_inputs
        print("Sending WPS Execute request to: " + wps_url)

        # call the wps and receive response
        r = get(wps_url)
        tree = ElementTree.fromstring(r.text)

        # wait for the response
        if "statusLocation" in tree.attrib:

            # process is started
            result = {"status": "OK",
                      "message": "Checking task has started and it is running in the background. "
                                 "To view status of the task, go to 'Checking Tasks' menu..."}
            js = json.dumps(result)
            return HttpResponse(js, content_type='application/json')
        else:

            # process failed to start
            error_response = {"status": "ERR", "message": "There was an error starting the process. Exception: %s" % r.text}
            js = json.dumps(error_response)
            return HttpResponse(js, content_type='application/json')

    except RequestException as e:  # catch exception in case of wps server not responding
        error_response = {"status": "ERR", "message": "WPS server probably does not respond. Error details: %s" % (e)}
        js = json.dumps(error_response)
        return HttpResponse(js, content_type='application/json')
