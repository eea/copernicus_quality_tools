# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import json
from django.http import HttpResponse
from django.http import JsonResponse
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


def jobs_json(request):

    data = list(Job.objects.values())
    cnt = len(data)
    resp = {"total": cnt, "rows": data}
    return JsonResponse(resp, safe=False)


def wps_execute_test(request):

    xml_file = os.path.join(os.path.abspath(os.path.dirname('__file__')), 'wps_response.xml')
    return HttpResponse(open(xml_file).read(), content_type='text/xml')

