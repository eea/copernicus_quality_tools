# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
import random
import requests
import sys
import time
import traceback
from xml.etree import ElementTree
from django.db import connection
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

def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
        ]

def tasks_json(request):

    all_tasks = CheckingSession.objects.all()

    # refreshing the status of the list
    namespaces = {'wps': 'http://www.opengis.net/wps/1.0.0', 'ows': 'http://schemas.opengis.net/ows/1.0.0'}
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
                    failed_tags = status_tag.findall('wps:ProcessFailed', namespaces)

                    if len(succeeded_tags) > 0:
                        print('process succeeded!')
                        obj.status = 'succeeded'
                        obj.log_info = succeeded_tags[0].text
                        obj.end = parse_datetime(status_tag.attrib['creationTime'])
                        obj.percent_complete = "100"
                        print(obj.log_info)

                    elif len(failed_tags) > 0:
                        print('process failed!')
                        obj.status = 'failed'
                        obj.end = parse_datetime(status_tag.attrib['creationTime'])
                        print(obj.end)
                        failed_tag = failed_tags[0]

                        # saving the exception text here
                        exception_tags = failed_tag.findall('wps:ExceptionReport', namespaces)
                        exception_tag = exception_tags[0]
                        for sub_tag in exception_tag:
                            print(sub_tag)
                            for detail_tag in sub_tag:
                                print(detail_tag.text)
                                obj.log_info = detail_tag.text

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
            except Exception:
                print(traceback.format_exc())
                obj.status = 'error'
                obj.save()

    # now create the table based on the SQL jquery
    offset = int(request.GET.get("offset") or 0)
    limit = int(request.GET.get("limit") or 50)
    sort = request.GET.get("sort") or "start"
    sort = "s." + sort
    order = request.GET.get("order") or ""
    search = request.GET.get("search") or None
    cond = ""
    order = """ ORDER BY %s %s""" % (sort, order)

    # number of all tasks
    sql = "SELECT Count(id) AS cnt FROM dashboard_checkingsession AS r WHERE 1=1 {0};".format(cond)
    with connection.cursor() as cur:
        cur.execute(sql)
        cnts = dictfetchall(cur)
    cnt = cnts[0]["cnt"]

    with connection.cursor() as cur:
        sql = """SELECT s.id, s.name, s.description, s.start, s.end, s.status,
      s.percent_complete, f.path, s.layer, p.name AS "product_name"
      FROM dashboard_checkingsession AS s
      LEFT JOIN dashboard_file AS f ON (s.file_id=f.id)
      LEFT JOIN dashboard_product AS p ON (s.product_id=p.id)
      WHERE 1=1 %s
      GROUP BY s.id, s.name, s.description, s.start, s.end, s.layer
      %s LIMIT %s;""" % (cond, order, limit)
        print(sql)
        cur.execute(sql)
        results = dictfetchall(cur)

    if results:
        results = list(results)
        i = 0
        for r in results:
            if r["name"]:
                results[i]["name"] = """<a title='Details...' href='#' onclick='run_details(%s, %s, %d)'><span class='glyphicon glyphicon-new-window' aria-hidden='true'></span> %s</a>""" % (r["id"], str(r["name"]), True, r["name"])
            i += 1
        data = {"total": cnt, "rows": results}
    else:
        data = {"total": cnt, "rows": []}

    #data = list(CheckingSession.objects.values())
    #cnt = len(data)
    #resp = {"total": cnt, "rows": data}
    return JsonResponse(data, safe=False)


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
    # use random delay (between 5 and 60 seconds)
    random_delay = int(random.random() * 20.0)
    random_cycles = int(random.random() * 20.0)

    # use random exit_ok
    random_01 = random.random()
    if random_01 < 0.8:
        random_exit_ok = 'true'
    else:
        random_exit_ok = 'false'

    wps_server = "http://192.168.2.72:5000"
    wps_base = wps_server + "/wps?service=WPS&version=1.0.0&request=Execute&identifier=cop_sleep"
    wps_url = wps_base + "&DataInputs=delay={0};cycles={1};exit_ok={2};filepath={3};layer_name={4};product_type_name={5}&lineage=true&status=true&storeExecuteResponse=true".format(
        random_delay, random_cycles, random_exit_ok, filepath, product_type_name, layer_name
    )

    print(wps_url)

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
