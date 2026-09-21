"""Stable facade for QC job/product unit lifecycle services."""

import logging

from .artifacts import load_product_unit_result_document
from .jobs import create_delivery_job as _create_delivery_job
from .jobs import refresh_delivery_projection as _refresh_delivery_projection
from .jobs import update_job_status as _update_job_status


logger = logging.getLogger(__name__)


def create_delivery_job(delivery, **kwargs):
    """Create a QC job with shared logging and row locking."""

    return _create_delivery_job(delivery, logger=logger, **kwargs)


def refresh_delivery_projection(delivery):
    """Refresh the delivery projection through the row-locked service."""

    return _refresh_delivery_projection(delivery)


def update_job_status(job, job_status):
    """Delegate terminal processing with patchable artifact loading/logging."""

    return _update_job_status(
        job,
        job_status,
        load_result_document=load_product_unit_result_document,
        logger=logger,
    )
