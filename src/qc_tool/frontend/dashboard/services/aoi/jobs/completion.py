"""Atomic terminal QC result processing and one-ZIP AOI enforcement."""

from django.db import transaction
from django.utils import timezone

from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING

from ..errors import AoiResultUnavailable
from ..projections import sync_locked_delivery_from_latest_job
from ..results import apply_result_aoi
from .metadata import apply_result_metadata


def update_job_status(
    job,
    job_status,
    *,
    load_result_document,
    logger,
):
    """Persist status/result facts and refresh the delivery projection."""

    Delivery = job._meta.apps.get_model("dashboard", "Delivery")
    with transaction.atomic():
        delivery = Delivery.objects.select_for_update().get(
            pk=job.delivery_id
        )
        job.refresh_from_db(
            fields=(
                "job_status",
                "aoi_code",
                "aoi_code_submitted",
                "date_finished",
            )
        )
        if job.job_status not in (JOB_WAITING, JOB_RUNNING):
            if job_status != job.job_status:
                logger.warning(
                    "Ignored status change for terminal job %s: %s -> %s",
                    job.job_uuid,
                    job.job_status,
                    job_status,
                )
            sync_locked_delivery_from_latest_job(delivery)
            return
        job.job_status = job_status
        updated_fields = ["job_status"]

        if job_status not in (JOB_WAITING, JOB_RUNNING):
            _set_finished_time(job, updated_fields)
            _apply_terminal_result(
                job,
                delivery,
                updated_fields,
                load_result_document=load_result_document,
                logger=logger,
            )
        job.save(update_fields=tuple(dict.fromkeys(updated_fields)))
        sync_locked_delivery_from_latest_job(delivery)


def _set_finished_time(job, updated_fields):
    if job.date_finished is None:
        job.date_finished = timezone.now()
        updated_fields.append("date_finished")


def _apply_terminal_result(
    job,
    delivery,
    updated_fields,
    *,
    load_result_document,
    logger,
):
    try:
        job_result = load_result_document(job.job_uuid)
    except AoiResultUnavailable as exc:
        logger.warning(
            "Could not load result metadata for job %s: %s",
            job.job_uuid,
            exc,
        )
    else:
        updated_fields.extend(apply_result_aoi(job, job_result))
        updated_fields.extend(apply_result_metadata(job, job_result))
        _reject_contradictory_aoi(job, delivery, logger=logger)

    if job.job_status == JOB_OK and not job.aoi_code_submitted:
        logger.error(
            "Successful job %s did not report one submitted AOI.",
            job.job_uuid,
        )
        job.job_status = JOB_ERROR


def _reject_contradictory_aoi(job, delivery, *, logger):
    if (
        delivery.aoi_code_submitted
        and job.aoi_code_submitted
        and delivery.aoi_code_submitted != job.aoi_code_submitted
    ):
        logger.error(
            "Conflicting submitted AOI for delivery %s: %s != %s",
            delivery.pk,
            delivery.aoi_code_submitted,
            job.aoi_code_submitted,
        )
        job.job_status = JOB_ERROR
