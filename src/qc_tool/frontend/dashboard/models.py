# -*- coding: utf-8 -*-
import uuid

from django.db import models
from django.utils import timezone

class Delivery(models.Model):
    class Meta:
        app_label = "dashboard"

    def __str__(self):
        return "User: {:s} | File: {:s}".format(self.user.username, self.filename)

    def user_directory_path(instance, filename):
        # file will be uploaded to MEDIA_ROOT/<username>/<filename>
        return '{0}/{1}'.format(instance.user.username, filename)

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