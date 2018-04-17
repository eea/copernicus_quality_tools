# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
import requests
import time
from xml.etree import ElementTree
from django.http import HttpResponse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import *
from .forms import *

from django.shortcuts import render

# Create your views here.

def new_check(request):

    return render(request, 'dashboard/new_check.html')


def job_list(request):

    form = JobForm()

    return render(request, 'dashboard/homepage.html', {'form': form, 'show_button': True})

    #jobs = Job.objects.filter(pk=1)
    #js = json.dumps(jobs)
    #return HttpResponse(js, content_type='application/json')


def tasks_json(request):

    data = list(CheckingSession.objects.values())
    cnt = len(data)
    resp = {"total": cnt, "rows": data}
    return JsonResponse(resp, safe=False)


@csrf_exempt
def run_wps_execute(request):
    """
    Called from the web app - Run the process
    """
    result = {"status": "OK", "message": "Checking task has started and it is running in the background. To view status of the task, go to 'Checking Tasks' menu..."}

    layer_name = request.POST.get("layer_name")
    product_type_name = request.POST.get("product_type_name")
    filepath = request.POST.get("filepath")

    user_id = request.user.id

    # try to call WPS on the external server
    wps_server = "http://192.168.2.72:5000"
    wps_base = wps_server + "/wps?service=WPS&version=1.0.0&request=Execute&identifier=cop_sleep";
    wps_url = wps_base + "&DataInputs=delay=1.3;cycles=10;exit_ok=true;filepath=/home/bum/bac;layer_name=my_layer;product_type_name=big_product&lineage=true&status=true&storeExecuteResponse=true"

    err = False
    try:
        r = requests.get(wps_url)
        print(r.text)
        tree = ElementTree.fromstring(r.text)

        # check if WPS response is valid
        n_tasks = CheckingSession.objects.count()

        if 'statusLocation' in tree.attrib:
            js = json.dumps(result)

            # save info about started checking session into the database
            task = CheckingSession()
            task.user = request.user
            task.name = 'Checking_{0}'.format(n_tasks + 1)
            task.description = 'test'
            task.product = Product.objects.first() #TODO set according to user request
            task.file = File.objects.first()       #TODO set according to user request
            task.layer = "layer_1"                 #TODO set according to user request
            task.status = "accepted"
            task.wps_status_location = tree.attrib["statusLocation"]
            task.wps_request = wps_url
            task.save()

            time.sleep(2)
            return HttpResponse(js, content_type='application/json')
        else:

            # save info about checking session with error into the database
            task = CheckingSession()
            task.user = request.user
            task.name = 'Checking_{0}'.format(n_tasks + 1)
            task.description = 'test'
            task.product = Product.objects.first()  # TODO set according to user request
            task.file = File.objects.first()  # TODO set according to user request
            task.layer = "layer_1"  # TODO set according to user request
            task.status = "error"
            task.wps_status_location = None
            task.wps_request = wps_url
            task.log_info = r.text
            task.save()

            error_response = {"status": "ERR", "message": "There was an error starting the process. Exception: %s" % r.text}
            js = json.dumps(error_response)

            time.sleep(2)
            return HttpResponse(js, content_type='application/json')

    except BaseException as e:

        error_response = {"status": "ERR", "message": "WPS server probably does not respond. Error details: %s" % (e)}
        js = json.dumps(error_response)
        return HttpResponse(js, content_type='application/json')