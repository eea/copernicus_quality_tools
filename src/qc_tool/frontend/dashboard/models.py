# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models
from django.utils import timezone

from django.utils.timezone import now


class FileFormat(models.Model):
    type = models.TextField()
    extension = models.TextField()
    description = models.TextField()

    def __str__(self):
        return self.type


class File(models.Model):
    path = models.TextField(max_length=500)
    storage = models.CharField(max_length=500)
    version = models.CharField(max_length=50)
    format = models.ForeignKey(FileFormat, null=True, on_delete=models.CASCADE)
    layers = models.CharField(blank=True, null=True, max_length=200)


class Product(models.Model):
    name = models.TextField(unique=True)
    description = models.TextField()
    file_format = models.ForeignKey(FileFormat, null=True, on_delete=models.CASCADE)

    def __str__(self):
        return self.name


class CheckingSession(models.Model):
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
