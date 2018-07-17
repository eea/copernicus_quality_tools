# -*- coding: utf-8 -*-
import json

from django.db import models
from django.utils import timezone

from qc_tool.common import prepare_empty_job_status
from qc_tool.common import compose_wps_status_filepath
from qc_tool.common import compose_job_status_filepath
from qc_tool.frontend.dashboard.helpers import parse_status_document

class Delivery(models.Model):
    class Meta:
        app_label = "dashboard"

    def __str__(self):
        return "User: {:s} | File: {:s}".format(self.user.username, self.filename)

    def user_directory_path(instance, filename):
        # file will be uploaded to MEDIA_ROOT/<username>/<filename>
        return '{0}/{1}'.format(instance.user.username, filename)

    def init_status(self, product_ident):
        # initializes the status with an empty job status document.
        self.last_wps_status = "accepted"
        self.last_job_status = "running"
        self.product_ident = product_ident
        self.empty_status_document = json.dumps(prepare_empty_job_status(product_ident))
        self.save()

    def update_status(self, job_uuid):

        self.last_job_uuid = job_uuid
        # updates the status using the status of the job uuid.
        # get job info from status document (assuming document exists)
        wps_status_filepath = compose_wps_status_filepath(job_uuid)
        wps_status = wps_status_filepath.read_text()
        wps_doc = parse_status_document(wps_status)

        # (1) Exception in job status document - run has stopped
        self.last_wps_status = wps_doc["status"]
        self.last_job_status = self.last_wps_status

        self.date_last_checked = wps_doc["end_time"]

        job_status_filepath = compose_job_status_filepath(job_uuid)
        job_info = {"status": None}
        if job_status_filepath.exists():
            job_info = job_status_filepath.read_text()
            job_info = json.loads(job_info)

            if (self.last_wps_status == "error"
                or job_info["exception"] is not None):
                self.last_job_status = "error"
                self.last_job_percent = 100
            elif self.last_wps_status == "accepted":
                self.last_job_status = "running"
                self.last_job_percent = wps_doc["percent_complete"]
            elif self.last_wps_status == "started":
                self.last_job_status = "running"
                self.last_job_percent = wps_doc["percent_complete"]
            elif any((check["status"] in ("failed", "aborted") for check in job_info["checks"])):
                self.last_job_status = "failed"
                self.last_job_percent = 100
            elif any((check["status"] is None or check["status"] == "skipped" for check in job_info["checks"])):
                self.last_job_status = "partial"
                self.last_job_percent = 100
            elif all((check["status"] == "ok" for check in job_info["checks"])):
                self.last_job_status = "ok"
                self.last_job_percent = 100
            else:
                self.last_job_status = None

        self.save()

        # return JsonResponse()
        return {"job_status": self.last_job_status, "wps_doc_status": self.last_wps_status, "percent": self.last_job_percent}

    filename = models.CharField(max_length=500)
    filepath = models.CharField(max_length=500)
    #file = models.FileField(models.FileField(upload_to=user_directory_path))
    product_ident = models.CharField(max_length=64, blank=True, null=True)
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
