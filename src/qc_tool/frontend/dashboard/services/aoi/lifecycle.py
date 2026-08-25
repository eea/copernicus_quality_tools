"""Transactional AOI lifecycle hooks used by the Delivery and Job models."""

import logging

from django.db import transaction
from django.utils import timezone

from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING

from .artifacts import load_aoi_result_document
from .errors import AoiResultUnavailable
from .projections import sync_locked_delivery_from_latest_job
from .results import apply_result_aoi


logger = logging.getLogger(__name__)


def create_delivery_job(
    delivery,
    *,
    product_ident,
    product_description,
    skip_steps,
):
    """Create a job and reset/project the delivery under one row lock."""

    Delivery = delivery._meta.model
    Job = delivery._meta.apps.get_model("dashboard", "Job")
    with transaction.atomic():
        locked_delivery = Delivery.objects.select_for_update().get(
            pk=delivery.pk
        )
        job = Job.objects.create(
            date_created=timezone.now(),
            job_status=JOB_WAITING,
            product_ident=product_ident,
            product_description=product_description,
            skip_steps=skip_steps,
            delivery=locked_delivery,
        )
        sync_locked_delivery_from_latest_job(locked_delivery)

    for field_name in ("product_ident", "product_description", "aoi_code"):
        setattr(delivery, field_name, getattr(locked_delivery, field_name))
    return job


def refresh_delivery_projection(delivery):
    """Safely refresh one delivery from its deterministic latest job."""

    Delivery = delivery._meta.model
    with transaction.atomic():
        locked_delivery = Delivery.objects.select_for_update().get(
            pk=delivery.pk
        )
        updated_fields = sync_locked_delivery_from_latest_job(locked_delivery)

    for field_name in ("product_ident", "product_description", "aoi_code"):
        setattr(delivery, field_name, getattr(locked_delivery, field_name))
    return updated_fields


def update_job_status(job, job_status):
    """Persist status/result AOI and refresh the delivery projection safely."""

    Delivery = job._meta.apps.get_model("dashboard", "Delivery")
    with transaction.atomic():
        delivery = Delivery.objects.select_for_update().get(
            pk=job.delivery_id
        )
        job.refresh_from_db(fields=("aoi_code", "date_finished"))
        job.job_status = job_status
        updated_fields = ["job_status"]

        if job_status not in (JOB_WAITING, JOB_RUNNING):
            if job.date_finished is None:
                job.date_finished = timezone.now()
                updated_fields.append("date_finished")
            try:
                job_result = load_aoi_result_document(job.job_uuid)
            except AoiResultUnavailable as exc:
                logger.warning(
                    "Could not load result metadata for job %s: %s",
                    job.job_uuid,
                    exc,
                )
            else:
                updated_fields.extend(apply_result_aoi(job, job_result))

        job.save(update_fields=tuple(dict.fromkeys(updated_fields)))
        sync_locked_delivery_from_latest_job(delivery)
