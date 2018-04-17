# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
import requests
import time
from xml.etree import ElementTree
from django.http import HttpResponse
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
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

    all_tasks = CheckingSession.objects.all()

    # refreshing the status of the list
    namespaces = {'wps': 'http://www.opengis.net/wps/1.0.0'}
    for obj in all_tasks:
        status = obj.status
        if status == 'accepted' or status == 'started':
            status_location_url = obj.wps_status_location
            try:
                r = requests.get(status_location_url)
                tree = ElementTree.fromstring(r.text)
                status_tags = tree.findall('wps:Status', namespaces)
                if len(status_tags) == 0:
                    # this meens there is no status element --- some exception ...
                    obj.status = 'error'

                else:
                    status_tag = status_tags[0]

                    accepted_tags = status_tag.findall('wps:ProcessAccepted', namespaces)
                    started_tags = status_tag.findall('wps:ProcessStarted', namespaces)
                    succeeded_tags = status_tag.findall('wps:ProcessSucceeded', namespaces)

                    if len(succeeded_tags) > 0:
                        print('process succeeded!')
                        obj.status = 'succeeded'
                        obj.log_info = succeeded_tags[0].text
                        obj.end = parse_datetime(status_tag.attrib['creationTime'])
                        obj.percent_complete = "100"
                        print(obj.log_info)
                        print(obj.end)

                    elif len(started_tags) > 0:
                        print('process started!')
                        obj.status = 'started'

                        started_tag = started_tags[0]
                        obj.log_info = started_tag.text

                        # also updating PercentComplete info
                        if "percentCompleted" in started_tag.attrib:
                            obj.percent_complete = started_tag.attrib["percentCompleted"]
                        else:
                            obj.percent_complete = "50"

                        print(obj.log_info)

                    elif len(accepted_tags) > 0:
                        obj.status = 'accepted'
                        obj.log_info = accepted_tags[0].text
                        print(obj.log_info)

                # save the new status of the object
                obj.save()
            except:
                obj.status = 'error'
                obj.save()

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
    wps_url = wps_base + "&DataInputs=delay=10;cycles=10;exit_ok=true;filepath=/home/bum/bac;layer_name=my_layer;product_type_name=big_product&lineage=true&status=true&storeExecuteResponse=true"

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
            task.percent_complete = "0"
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
            task.percent_complete = "0"
            task.save()

            error_response = {"status": "ERR", "message": "There was an error starting the process. Exception: %s" % r.text}
            js = json.dumps(error_response)

            time.sleep(2)
            return HttpResponse(js, content_type='application/json')

    except BaseException as e:

        error_response = {"status": "ERR", "message": "WPS server probably does not respond. Error details: %s" % (e)}
        js = json.dumps(error_response)
        return HttpResponse(js, content_type='application/json')