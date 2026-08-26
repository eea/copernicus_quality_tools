"""Remote delivery storage coordinates and credentials."""

from django.db import models


class S3Info(models.Model):
    host = models.CharField(max_length=200)
    access_key = models.CharField(max_length=100)
    secret_key = models.CharField(max_length=100)
    bucketname = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=500)

    class Meta:
        app_label = "dashboard"
