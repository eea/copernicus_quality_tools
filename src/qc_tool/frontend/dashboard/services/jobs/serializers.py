"""Explicit public projections for job records and reports."""

from qc_tool.aoi import is_aoi_input_alias
from qc_tool.common import JOB_ERROR


MISSING_RESULT_ERROR_MESSAGE = (
    "The QC worker stopped before producing a result document. Review the "
    "job log or contact an administrator and provide this job identifier."
)


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
            "aoi_code": job.aoi_code,
            "aoi_code_submitted": getattr(job, "aoi_code_submitted", None),
            "skip_steps": job.skip_steps,
        }
        for job in jobs
    ]


def serialize_job_report(job_report, job):
    """Return one safe report backed by authoritative persisted job facts.

    A worker process can terminate before it writes ``result.json``. The
    product blueprint used for that case contains empty presentation fields;
    fill those fields from PostgreSQL and expose an actionable, non-sensitive
    error instead of rendering ``None`` values.
    """

    serialized = (
        {
            key: value
            for key, value in job_report.items()
            if not is_aoi_input_alias(key)
        }
        if isinstance(job_report, dict)
        else {}
    )
    serialized["job_uuid"] = serialized.get("job_uuid") or job.job_uuid
    serialized["product_ident"] = job.product_ident
    serialized["description"] = (
        serialized.get("description") or job.product_description
    )
    serialized["filename"] = job.delivery.filename
    serialized["status"] = serialized.get("status") or job.job_status
    serialized["job_start_date"] = (
        serialized.get("job_start_date") or job.date_started
    )
    serialized["job_finish_date"] = (
        serialized.get("job_finish_date") or job.date_finished
    )
    serialized["reference_year"] = (
        serialized.get("reference_year") or job.reference_period or None
    )
    if not isinstance(serialized.get("steps"), list):
        serialized["steps"] = []
    if (
        serialized["status"] == JOB_ERROR
        and not _has_message(serialized.get("error_message"))
    ):
        serialized["error_message"] = MISSING_RESULT_ERROR_MESSAGE
    serialized["aoi_code"] = job.aoi_code
    serialized["aoi_code_submitted"] = getattr(
        job,
        "aoi_code_submitted",
        None,
    )
    return serialized


def _has_message(value):
    return isinstance(value, str) and bool(value.strip())


def _job_uuid(value, *, compact):
    serialized = str(value)
    return serialized.replace("-", "") if compact else serialized
