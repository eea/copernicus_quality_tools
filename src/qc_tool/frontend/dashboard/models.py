# -*- coding: utf-8 -*-


from pathlib import Path
from uuid import uuid4

import django.db.models as models
from django.utils import timezone

from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.helpers import find_product_description


def pull_job(worker_url):
    """
    UPDATE deliveries SET last_job_uuid=%s WHERE last_job_uuid IS NULL LIMIT 1
    :return:
    """

    # [:1] tells Django to add a " LIMIT 1" clause to the database query.
    deliveries = Delivery.objects.filter(last_job_status=JOB_WAITING)[:1]

    if len(deliveries) == 1:
        d = deliveries.get()

        # Safeguard against race condition. only return a non-null result if a row was updated in the database.
        affected_rowcount = (Delivery.objects.filter(last_job_status=JOB_WAITING, id=d.id)
                                             .update(last_job_status=JOB_RUNNING, worker_url=worker_url))

        if affected_rowcount == 1:
            # The job is available.
            d = Delivery.objects.get(id=d.id)
            return d
        else:
            # The job has already been taken by another worker.
            return None
    else:
        return None

class Delivery(models.Model):
    class Meta:
        app_label = "dashboard"

    def __str__(self):
        return "User: {:s} | File: {:s}".format(self.user.username, self.filename)

    def user_directory_path(instance, filename):
        # file will be uploaded to MEDIA_ROOT/<username>/<filename>
        return str(Path(instance.user.username, filename))

    def create_job(self, product_ident, skip_steps):
        self.last_job_uuid = str(uuid4())
        self.last_job_percent = 0
        self.last_job_status = JOB_WAITING
        self.product_ident = product_ident
        self.product_description = find_product_description(product_ident)
        self.skip_steps = skip_steps
        self.save()

    def update_job(self, job_status):
        self.last_job_status = job_status
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
    skip_steps = models.CharField(max_length=100, default=None, blank=True, null=True)
    last_job_uuid = models.CharField(max_length=32, default=None, blank=True, null=True)
    last_job_status = models.CharField(max_length=64, default=None, blank=True, null=True)
    last_job_percent = models.IntegerField(default=None, blank=True, null=True)
    worker_url = models.CharField(max_length=500, default=None, blank=True, null=True)
