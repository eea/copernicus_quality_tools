# -*- coding: utf-8 -*-


from pathlib import Path

from django.db import models
from django.utils import timezone

from qc_tool.common import check_running_job
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.dashboard.helpers import find_product_description


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
        self.last_job_status = JOB_RUNNING
        self.product_ident = product_ident
        self.product_description = find_product_description(product_ident)
        self.save()

    def update_job(self):
        (job_status, other) = check_running_job(self.last_job_uuid)
        self.last_job_status = job_status
        if job_status == JOB_RUNNING:
            self.last_job_percent = other
        self.save()

    def submit(self):
        self.date_submitted = timezone.now()
        self.save()

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
