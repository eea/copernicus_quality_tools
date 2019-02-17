# -*- coding: utf-8 -*-


import json
from datetime import datetime

from django.db import models
from django.utils import timezone

import qc_tool.frontend.dashboard.statuses as statuses
from qc_tool.common import compile_job_report
from qc_tool.common import has_job_expired
from qc_tool.common import load_job_result
from qc_tool.common import load_wps_status
from qc_tool.frontend.dashboard.helpers import find_product_description
from qc_tool.frontend.dashboard.helpers import parse_wps_status_document




class Delivery(models.Model):
    class Meta:
        app_label = "dashboard"

    def __str__(self):
        return "User: {:s} | File: {:s}".format(self.user.username, self.filename)

    def user_directory_path(instance, filename):
        # file will be uploaded to MEDIA_ROOT/<username>/<filename>
        return '{0}/{1}'.format(instance.user.username, filename)

    def init_status(self, product_ident):
        # initializes the status with an initial job result document.
        self.last_job_percent = 0
        self.last_wps_status = statuses.WPS_ACCEPTED
        self.last_job_status = statuses.JOB_RUNNING
        self.product_ident = product_ident
        self.product_description = find_product_description(product_ident)
        job_result = compile_job_report(product_ident=product_ident)
        self.empty_status_document = json.dumps(job_result)
        self.save()

    def update_status(self, job_uuid=None):
        if job_uuid is not None:
            self.last_job_uuid = job_uuid
        # Updates the status using the status of the job uuid.
        # Get job info from status document (assuming document exists)
        wps_status = load_wps_status(self.last_job_uuid)
        wps_doc = parse_wps_status_document(wps_status)

        self.last_wps_status = wps_doc["status"]
        self.date_last_checked = wps_doc["end_time"]

        # Determine job status with respect to wps status.
        if self.last_wps_status == statuses.WPS_ACCEPTED:
            self.last_job_percent = 0
            self.last_job_status = statuses.JOB_WAITING
        elif self.last_wps_status == statuses.WPS_STARTED:
            self.last_job_percent = wps_doc["percent_complete"]
            self.last_job_status = statuses.JOB_RUNNING
        elif self.last_wps_status == statuses.WPS_FAILED:
            self.last_job_percent = 100
            self.last_job_status = statuses.JOB_ERROR
        elif self.last_wps_status == statuses.WPS_SUCCEEDED:
            job_result = load_job_result(self.last_job_uuid)
            self.last_job_status = job_result["status"]
        else:
            self.last_job_status = None

        # Check expired job.
        if self.last_job_status == statuses.JOB_RUNNING:
            if has_job_expired(self.last_job_uuid):
                self.last_job_status = statuses.JOB_EXPIRED

        self.save()

        is_submitted = self.date_submitted is not None

        # return JsonResponse()
        return {"is_submitted": is_submitted,
                "job_status": self.last_job_status,
                "wps_doc_status": self.last_wps_status,
                "percent": self.last_job_percent}

    filename = models.CharField(max_length=500)
    filepath = models.CharField(max_length=500)
    size_bytes = models.IntegerField(null=True)
    product_ident = models.CharField(max_length=64, blank=True, null=True)
    product_description = models.CharField(max_length=500, blank=True, null=True)
    date_uploaded = models.DateTimeField(default=timezone.now)
    date_last_checked = models.DateTimeField(null=True)
    date_submitted = models.DateTimeField(null=True)
    last_wps_status = models.CharField(max_length=64)
    last_job_uuid = models.CharField(max_length=32)
    last_job_status = models.CharField(max_length=64)
    last_job_percent = models.IntegerField(null=True)
    empty_status_document = models.TextField()
    user = models.ForeignKey("auth.User", null=True, on_delete=models.CASCADE)


class Job(models.Model):
    class Meta:
        app_label = "dashboard"
    job_uuid = models.CharField(max_length=32)
    product_ident = models.CharField(max_length=64, null=True)
    start = models.DateTimeField(blank=True, null=True)
    end = models.DateTimeField(blank=True, null=True)
    wps_status = models.CharField(max_length=64)
    status = models.CharField(max_length=64)
    status_document_path = models.CharField(max_length=500)
    filename = models.CharField(blank=True, null=True, max_length=500)
    filepath = models.CharField(blank=True, null=True, max_length=500)
    user = models.ForeignKey("auth.User", null=True, on_delete=models.CASCADE)
