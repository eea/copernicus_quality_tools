# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
import requests
import time
import zipfile

from pathlib import Path
from xml.etree import ElementTree

from django.conf import settings
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import FileSystemStorage

from .helpers import parse_status_document
from .helpers import get_file_or_dir_size

from django.shortcuts import render
from django.shortcuts import redirect


def index(request):

    return render(request, 'dashboard/homepage.html', {'show_button': True})


def new_check(request):

    return render(request, 'dashboard/new_check.html')


def get_files_json(request):
    """
    returns a list of all files that are available for checking.
    The files are loaded from the directory specified in settings.CHECKED_FILES_DIR
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

        return redirect('/files/?uploaded_filename={0}'.format(myfile.name))

    return render(request, 'dashboard/file_upload.html')


def get_product_types(request):
    """
    returns a list of all product types that are available for checking.
    The files are loaded from the directory specified in settings.PRODUCT_TYPES_DIR
    :param request:
    :return: list of the product types with items {name, description} in JSON format
    """
    wps_host = settings.WPS_URL.rsplit('/', 1)[0]
    product_types_url = wps_host + "/product_types"
    resp = requests.get(url=product_types_url)
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
    wps_host = settings.WPS_URL.rsplit('/', 1)[0]
    product_types_url = wps_host + "/product_types"
    resp = requests.get(url=product_types_url)
    product_types = resp.json()
    product_type_info = product_types[product_type_name]

    return JsonResponse({'product_type': product_type_info})


def get_product_type_table(request, product_type):
    """
    returns the product type info in suitable format for bootstrap-table
    :param request:
    :param product_type:
    :return:
    """
    prod_file = os.path.join(settings.PRODUCT_TYPES_DIR, product_type + ".json")
    prod_path = Path(prod_file)
    prod_info = json.loads(prod_path.read_text())
    checks = prod_info['checks']
    check_list = []
    for check in checks:
        if 'parameters' in check:
            check_params = repr(check['parameters'])
        else:
            check_params = 'no parameters'
        check_list.append({'check_ident': check['check_ident'],
                         'required': check['required'],
                         'parameters': check_params})
    return JsonResponse({"total": len(checks), "rows": check_list})


def get_result(request, result_uuid):

    # fetch the result status document
    wps_host = settings.WPS_URL.rsplit('/', 1)[0]
    status_doc_url = wps_host + '/output/' + result_uuid + '.xml'
    status_doc = parse_status_document(status_doc_url)
    result_detail = status_doc['result']

    print(result_detail)
    result_list = []
    for id, val in result_detail.items():
        result_list.append({'check_ident': id, 'status': val['status'], 'message': val.get('message')})

    # sort the results by check_ident
    result_list_sorted = sorted(result_list, key=lambda x: x['check_ident'])

    context = {
        'product_type_name': status_doc['product_type_name'],
        'product_type_description': None,
        'filepath': status_doc['filepath'],
        'start_time': status_doc['start_time'],
        'status_document_url': status_doc_url.replace("wps", "127.0.0.1"),
        'result': {
            'uuid': result_uuid,
            'detail': result_list_sorted
        }
    }
    return render(request, 'dashboard/result.html', context)


def get_checking_sessions(request):
    """
    Returns the list of all checking sessions in JSON format
    :param request:
    :return:
    """

    # first, retrieve the URL's
    wps_host = settings.WPS_URL.rsplit('/', 1)[0]
    status_docs_api = wps_host + "/status_document_urls"
    resp = requests.get(url=status_docs_api)
    status_doc_urls = resp.json()

    # for each status document, retrieve the info:
    docs = []
    for doc_url in status_doc_urls:
        doc_url2 = wps_host + "/output/" + doc_url.rsplit("/")[-1]
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

        # calling cop_sleep (-> change it to run_checks)
        wps_base_url = settings.WPS_URL # "http://192.168.2.72:5000"
        wps_base = wps_base_url + "?service=WPS&version=1.0.0&request=Execute&identifier=run_checks&lineage=true&DataInputs="
        data_inputs = "filepath={0};product_type_name={1};optional_check_idents={2}".format(filepath, product_type_name, optional_check_idents)

        wps_url = wps_base + data_inputs
        print('Sending WPS Execute request to: ' + wps_url)

        # call the wps and receive response
        r = requests.get(wps_url)
        tree = ElementTree.fromstring(r.text)

        # wait for the response
        if 'statusLocation' in tree.attrib:

            # process is started
            result = {"status": "OK",
                      "message": "Checking task has started and it is running in the background. " +
                                 "To view status of the task, go to 'Checking Tasks' menu..."}
            js = json.dumps(result)
            return HttpResponse(js, content_type='application/json')
        else:

            # process failed to start
            error_response = {"status": "ERR", "message": "There was an error starting the process. Exception: %s" % r.text}
            js = json.dumps(error_response)
            return HttpResponse(js, content_type='application/json')

    except requests.exceptions.RequestException as e:  # catch exception in case of wps server not responding
        error_response = {"status": "ERR", "message": "WPS server probably does not respond. Error details: %s" % (e)}
        js = json.dumps(error_response)
        return HttpResponse(js, content_type='application/json')
