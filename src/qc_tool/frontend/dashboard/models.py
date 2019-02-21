# -*- coding: utf-8 -*-


import json
from datetime import datetime
from pathlib import Path

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
        return str(Path(instance.user.username, filename))

    def init_job(self, product_ident, job_uuid):
        self.last_job_uuid = job_uuid
        self.last_job_percent = 0
        self.last_job_status = statuses.JOB_RUNNING
        self.product_ident = product_ident
        self.product_description = find_product_description(product_ident)
        self.save()

    def update_job(self):
        # Updates the status using the status of the job uuid.
        wps_status = load_wps_status(self.last_job_uuid)
        wps_status = parse_wps_status_document(wps_status)
        wps_percent = wps_status["percent_complete"]
        wps_status = wps_status["status"]

        # Determine job status with respect to wps status.
        if wps_status == statuses.WPS_ACCEPTED:
            self.last_job_percent = 0
            self.last_job_status = statuses.JOB_WAITING
        elif wps_status == statuses.WPS_STARTED:
            self.last_job_percent = wps_percent
            self.last_job_status = statuses.JOB_RUNNING
        elif wps_status == statuses.WPS_FAILED:
            self.last_job_percent = 100
            self.last_job_status = statuses.JOB_ERROR
        elif wps_status == statuses.WPS_SUCCEEDED:
            job_result = load_job_result(self.last_job_uuid)
            self.last_job_status = job_result["status"]
        else:
            self.last_job_status = None

        # Check expired job.
        if self.last_job_status == statuses.JOB_RUNNING:
            if has_job_expired(self.last_job_uuid):
                self.last_job_status = statuses.JOB_EXPIRED

        # Write changes to database.
        self.save()


    def submit(self):
        self.date_submitted = timezone.now()

    def is_submitted(self):
        return self.date_submitted is not None

    user = models.ForeignKey("auth.User", null=True, on_delete=models.CASCADE)
    filename = models.CharField(max_length=500)
    filepath = models.CharField(max_length=500)
    size_bytes = models.IntegerField()
    date_uploaded = models.DateTimeField(default=timezone.now)
    date_submitted = models.DateTimeField(blank=True, null=True)
    product_ident = models.CharField(max_length=64, default=None, blank=True, null=True)
    product_description = models.CharField(max_length=500, default=None, blank=True, null=True)
    last_job_uuid = models.CharField(max_length=32, default=None, blank=True, null=True)
    last_job_status = models.CharField(max_length=64, default=None, blank=True, null=True)
    last_job_percent = models.IntegerField(default=None, blank=True, null=True)
