# -*- coding: utf-8 -*-
import json
from datetime import datetime

from django.db import models
from django.utils import timezone

from qc_tool.common import load_product_definition
from qc_tool.common import prepare_job_result
from qc_tool.common import compose_wps_status_filepath
from qc_tool.common import compose_job_result_filepath
from qc_tool.frontend.dashboard import statuses
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
        product_definition = load_product_definition(product_ident)
        job_result = prepare_job_result(product_definition)
        self.empty_status_document = json.dumps(job_result)
        self.save()

    def update_status(self, job_uuid=None):

        if job_uuid is not None:
            self.last_job_uuid = job_uuid
        # Updates the status using the status of the job uuid.
        # Get job info from status document (assuming document exists)
        wps_status_filepath = compose_wps_status_filepath(self.last_job_uuid)
        wps_status = wps_status_filepath.read_text()
        wps_doc = parse_wps_status_document(wps_status)

        self.last_wps_status = wps_doc["status"]
        self.last_job_status = self.last_wps_status

        self.date_last_checked = wps_doc["end_time"]

        job_result_filepath = compose_job_result_filepath(self.last_job_uuid)
        if job_result_filepath.exists():
            job_result = job_result_filepath.read_text()
            job_result = json.loads(job_result)

            # Set progress percent (from wps doc)
            if self.last_wps_status == statuses.WPS_ACCEPTED:
                self.last_job_percent = 0
            elif self.last_wps_status == statuses.WPS_STARTED:
                self.last_job_percent = wps_doc["percent_complete"]
            elif self.last_wps_status in (statuses.WPS_SUCCEEDED, statuses.WPS_FAILED):
                self.last_job_percent = 100
            else:
                self.last_job_percent = 0

            # Set status (from job status doc)
            if (self.last_wps_status == statuses.WPS_FAILED
                or job_result["exception"] is not None):
                self.last_job_status = statuses.JOB_ERROR
            elif self.last_wps_status in(statuses.WPS_ACCEPTED, statuses.WPS_STARTED):
                self.last_job_status = statuses.JOB_RUNNING
            elif any((step_result["status"] in ("failed", "aborted") for step_result in job_result["steps"])):
                self.last_job_status = statuses.JOB_FAILED
            elif any((step_result["status"] is None or step_result["status"] == "skipped" for step_result in job_result["steps"])):
                self.last_job_status = statuses.JOB_PARTIAL
            elif all((step_result["status"] == "ok" for step_result in job_result["steps"])):
                self.last_job_status = statuses.JOB_OK
            else:
                self.last_job_status = None

            # Check expired job
            # expire_timeout_s = 86400
            expire_timeout_s = 43200
            if self.last_job_status == statuses.JOB_RUNNING:
                job_timestamp = job_result_filepath.stat().st_mtime
                job_last_updated = datetime.utcfromtimestamp(job_timestamp)
                if (datetime.now() - job_last_updated).total_seconds() > expire_timeout_s:
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
