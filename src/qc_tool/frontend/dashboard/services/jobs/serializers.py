"""Explicit public projections for job records."""


def serialize_job_history(jobs, *, compact_uuid=False):
    """Serialize only fields intended for browser/API history consumers.

    In particular, internal worker URLs are never exposed by relying on
    ``QuerySet.values()`` over every model field.
    """

    return [
        {
            "job_uuid": _job_uuid(job.job_uuid, compact=compact_uuid),
            "delivery_id": job.delivery_id,
            "date_created": job.date_created,
            "date_started": job.date_started,
            "date_finished": job.date_finished,
            "job_status": job.job_status,
            "product_ident": job.product_ident,
            "product_description": job.product_description,
            "skip_steps": job.skip_steps,
        }
        for job in jobs
    ]


def _job_uuid(value, *, compact):
    serialized = str(value)
    return serialized.replace("-", "") if compact else serialized
