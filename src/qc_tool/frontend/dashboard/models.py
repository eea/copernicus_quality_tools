# -*- coding: utf-8 -*-


import logging
from pathlib import Path
from uuid import uuid4

import django.db.models as models
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User


from qc_tool.aoi import normalize_aoi_code
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.common import load_job_result
from qc_tool.frontend.dashboard.helpers import find_product_description


logger = logging.getLogger(__name__)

AOI_CODE_MAX_LENGTH = 255


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


class ApiUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    api_key = models.CharField(max_length=100)


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    country = models.CharField(max_length=100, blank=True, null=True)
    product_family = models.CharField(max_length=50, blank=True, null=True)


class S3Info(models.Model):
    host = models.CharField(max_length=200)
    access_key = models.CharField(max_length=100)
    secret_key = models.CharField(max_length=100)
    bucketname = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=500)


class Delivery(models.Model):
    class Meta:
        app_label = "dashboard"
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"

    def __str__(self):
        return "User: {:s} | File: {:s}".format(self.user.username, self.filename)

    def create_job(self, product_ident, skip_steps):
        product_description = find_product_description(product_ident)
        with transaction.atomic():
            delivery = Delivery.objects.select_for_update().get(pk=self.pk)
            job = Job.objects.create(
                date_created=timezone.now(),
                job_status=JOB_WAITING,
                product_ident=product_ident,
                product_description=product_description,
                skip_steps=skip_steps,
                delivery=delivery,
            )
            delivery.sync_from_latest_job()

        # Preserve the existing behavior where the caller's instance reflects
        # the delivery-level metadata written while creating the job.
        self.product_ident = delivery.product_ident
        self.product_description = delivery.product_description
        self.aoi_code = delivery.aoi_code

        # Return formatted uuid of the newly created job
        return str(job.job_uuid).lower().replace("-", "")

    def sync_from_latest_job(self):
        """Project the latest-created job's canonical metadata onto delivery.

        Callers that mutate jobs must hold a row lock on this delivery so the
        cached projection cannot race with another job update.
        """
        latest_job = (Job.objects.filter(delivery_id=self.pk)
                      .order_by("-date_created", "-job_uuid")
                      .only("aoi_code", "product_ident", "product_description")
                      .first())

        updated_fields = []
        aoi_code = normalize_aoi_code(latest_job.aoi_code) if latest_job else None
        if self.aoi_code != aoi_code:
            self.aoi_code = aoi_code
            updated_fields.append("aoi_code")

        if latest_job is not None:
            for field_name in ("product_ident", "product_description"):
                value = getattr(latest_job, field_name)
                if getattr(self, field_name) != value:
                    setattr(self, field_name, value)
                    updated_fields.append(field_name)

        if updated_fields:
            self.save(update_fields=updated_fields)
        return updated_fields

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
    size_bytes = models.BigIntegerField()
    date_uploaded = models.DateTimeField(default=timezone.now)
    date_submitted = models.DateTimeField(blank=True, null=True)
    product_ident = models.CharField(max_length=64, default=None, blank=True, null=True)
    product_description = models.CharField(max_length=500, default=None, blank=True, null=True)
    aoi_code = models.CharField(max_length=AOI_CODE_MAX_LENGTH, default=None, blank=True, null=True,
                                editable=False,
                                help_text="Canonical AOI code projected from the latest delivery job.")
    is_deleted = models.BooleanField(default=False)
    s3 = models.ForeignKey(S3Info, null=True, on_delete=models.CASCADE)


class Job(models.Model):
    class Meta:
        app_label = "dashboard"

    def __str__(self):
        return "{0} | {1} | {2}".format(str(self.job_uuid), self.delivery.filename, self.job_status)

    def apply_result_metadata(self, job_result):
        """Copy supported reporting metadata from a worker result onto this job.

        The method updates the model instance without saving it and returns the
        names of fields that changed. An absent or malformed value preserves
        stored metadata; an explicit null clears it as unavailable or ambiguous.
        """
        if not isinstance(job_result, dict):
            return []

        if "aoi_code" not in job_result:
            return []
        aoi_code = job_result["aoi_code"]
        if aoi_code is None:
            if self.aoi_code is None:
                return []
            self.aoi_code = None
            return ["aoi_code"]
        aoi_code = normalize_aoi_code(aoi_code)
        if aoi_code is None:
            return []
        if len(aoi_code) > AOI_CODE_MAX_LENGTH:
            return []
        if self.aoi_code == aoi_code:
            return []

        self.aoi_code = aoi_code
        return ["aoi_code"]

    def update_status(self, job_status):
        with transaction.atomic():
            delivery = Delivery.objects.select_for_update().get(pk=self.delivery_id)
            # Delivery is the shared lock for every job that can update its
            # projected metadata. Refresh values that must be write-once after
            # acquiring it so concurrent status pollers cannot use stale data.
            self.refresh_from_db(fields=("aoi_code", "date_finished"))
            self.job_status = job_status
            updated_fields = ["job_status"]
            if job_status not in (JOB_WAITING, JOB_RUNNING):
                if self.date_finished is None:
                    self.date_finished = timezone.now()
                    updated_fields.append("date_finished")
                try:
                    job_result = load_job_result(str(self.job_uuid))
                except (OSError, ValueError) as exc:
                    # TIMEOUT/LOST jobs may not have a readable result document.
                    # Their status still needs to be persisted.
                    logger.warning("Could not load result metadata for job %s: %s", self.job_uuid, exc)
                else:
                    updated_fields.extend(self.apply_result_metadata(job_result))
            self.save(update_fields=updated_fields)
            delivery.sync_from_latest_job()

    job_uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE)
    date_created = models.DateTimeField(default=timezone.now)
    date_started = models.DateTimeField(blank=True, null=True)
    date_finished = models.DateTimeField(blank=True, null=True)
    job_status = models.CharField(max_length=64, default=JOB_WAITING)
    product_ident = models.CharField(max_length=64)
    product_description = models.CharField(max_length=500)
    aoi_code = models.CharField(max_length=AOI_CODE_MAX_LENGTH, default=None, blank=True, null=True,
                                db_index=True, editable=False,
                                help_text="Canonical AOI code detected in the delivery job result.")
    skip_steps = models.CharField(max_length=100, default=None, blank=True, null=True)
    worker_url = models.CharField(max_length=500, default=None, blank=True, null=True)
