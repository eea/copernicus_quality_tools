# -*- coding: utf-8 -*-
import uuid

from django.db import models
from django.utils import timezone

class UploadedFile(models.Model):
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
    status = models.CharField(max_length=64)
    user = models.ForeignKey("auth.User", null=True, on_delete=models.CASCADE)


class Job(models.Model):
    class Meta:
        app_label = "dashboard"
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    job_uuid = models.CharField(max_length=32)
    product_ident = models.CharField(max_length=64, null=True)
    start = models.DateTimeField(blank=True, null=True)
    end = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=64)
    status_document_path = models.CharField(max_length=500)
    filename = models.CharField(blank=True, null=True, max_length=500)
    file = models.ForeignKey(UploadedFile, null=True, blank=True, on_delete=models.CASCADE)
    user = models.ForeignKey("auth.User", null=True, on_delete=models.CASCADE)


class FileFormat(models.Model):
    class Meta:
        app_label = "dashboard"
    type = models.TextField()
    extension = models.TextField()
    description = models.TextField()

    def __str__(self):
        return self.type


class File(models.Model):
    class Meta:
        app_label = "dashboard"
    path = models.TextField(max_length=500)
    storage = models.CharField(max_length=500)
    version = models.CharField(max_length=50)
    format = models.ForeignKey(FileFormat, null=True, on_delete=models.CASCADE)
    layers = models.CharField(blank=True, null=True, max_length=200)


class Product(models.Model):
    class Meta:
        app_label = "dashboard"
    name = models.TextField(unique=True)
    description = models.TextField()
    file_format = models.ForeignKey(FileFormat, null=True, on_delete=models.CASCADE)

    def __str__(self):
        return self.name


class CheckingSession(models.Model):
    class Meta:
        app_label = "dashboard"
    """
    The CheckingSession model: this is the main model for keeping track of
    the tasks
    """
    user = models.ForeignKey('auth.User', null=True, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField()

    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    file = models.ForeignKey(File, on_delete=models.CASCADE)

    layer = models.CharField(blank=True, max_length=200)

    start = models.DateTimeField(default=timezone.now)

    end = models.DateTimeField(blank=True, null=True)

    status = models.CharField(max_length=200)

    percent_complete = models.CharField(max_length=50, blank=True, null=True)

    wps_request = models.CharField(max_length=400, blank=True, null=True)

    wps_status_location = models.CharField(max_length=400, null=True)

    result = models.CharField(blank=True, null=True, max_length=200)

    log_info = models.TextField(blank=True, null=True)

    def publish(self):
        self.published_date = timezone.now()
        self.save()

    def __str__(self):
        return self.name + ' (' + self.status + ')'
