# -*- coding: utf-8 -*-


from pathlib import Path
from uuid import uuid4

import django.db.models as models
from django.utils import timezone

from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.helpers import find_product_description


def pull_job(worker_url):
    """
    UPDATE deliveries SET last_job_uuid=%s WHERE last_job_uuid IS NULL LIMIT 1
    :return:
    """

    # [:1] tells Django to add a " LIMIT 1" clause to the database query.
    jobs = Job.objects.filter(job_status=JOB_WAITING).order_by("date_created")[:1]

    if len(jobs) == 1:
        job = jobs.get()

        # Safeguard against race condition. only return a non-null result if a row was updated in the database.
        affected_rowcount = (Job.objects.filter(job_status=JOB_WAITING, job_uuid=job.job_uuid)
                                        .update(job_status=JOB_RUNNING, date_started=timezone.now(), worker_url=worker_url))

        if affected_rowcount == 1:
            # The job is available.
            job = Job.objects.get(job_uuid=job.job_uuid)
            return job
        else:
            # The job has already been taken by another worker.
            return None
    else:
        return None


class Delivery(models.Model):
    class Meta:
        app_label = "dashboard"
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"

    def __str__(self):
        return "User: {:s} | File: {:s}".format(self.user.username, self.filename)

    def create_job(self, product_ident, skip_steps):

        job = Job()
        job.date_created = timezone.now()
        job.job_status = JOB_WAITING
        job.product_ident = product_ident
        job.product_description = find_product_description(product_ident)
        job.skip_steps = skip_steps
        job.delivery = self
        job.save()

        # Also update delivery-level default product ident and product description.
        self.product_ident = job.product_ident
        self.product_description = job.product_description
        self.save()

        # Return uuid of the created job
        return job.job_uuid


    def get_submittable_job(self):
        jobs_to_submit = Job.objects.filter(delivery__id=self.id).filter(job_status=JOB_OK).order_by("-date_created")[:1]
        if len(jobs_to_submit) == 0:
            return None
        else:
            return jobs_to_submit[0]

    def submit(self):
        self.date_submitted = timezone.now()
        self.save()

    def is_submitted(self):
        return self.date_submitted is not None

    user = models.ForeignKey("auth.User", null=True, on_delete=models.CASCADE)
    filename = models.CharField(max_length=500)
    size_bytes = models.IntegerField()
    date_uploaded = models.DateTimeField(default=timezone.now)
    date_submitted = models.DateTimeField(blank=True, null=True)
    product_ident = models.CharField(max_length=64, default=None, blank=True, null=True)
    product_description = models.CharField(max_length=500, default=None, blank=True, null=True)
    is_deleted = models.BooleanField(default=False)


class Job(models.Model):
    class Meta:
        app_label = "dashboard"

    def __str__(self):
        return "{0} | {1} | {2}".format(str(self.job_uuid), self.delivery.filename, self.job_status)

    def update_status(self, job_status):
        self.job_status = job_status
        if job_status not in (JOB_WAITING, JOB_RUNNING):
            self.date_finished = timezone.now()
        self.save()

    job_uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    date_created = models.DateTimeField(default=timezone.now)
    date_started = models.DateTimeField(blank=True, null=True)
    date_finished = models.DateTimeField(blank=True, null=True)
    job_status = models.CharField(max_length=64, default=JOB_WAITING)
    product_ident = models.CharField(max_length=64)
    product_description = models.CharField(max_length=500)
    skip_steps = models.CharField(max_length=100, default=None, blank=True, null=True)
    worker_url = models.CharField(max_length=500, default=None, blank=True, null=True)
