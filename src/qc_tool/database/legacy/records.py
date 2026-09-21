"""Convert historical execution records without inventing retained QC evidence."""

from collections import Counter
from uuid import UUID

from qc_tool.common import (
    JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL,
    JOB_RUNNING, JOB_TIMEOUT, JOB_WAITING,
)
from qc_tool.frontend.dashboard.models import Delivery, Job, S3Info
from qc_tool.product_units import legacy_aoi_to_product_unit_code

from .values import boolean, bounded_text, integer, timestamp


_COLUMNS = {
    "dashboard_delivery": {
        "id", "filename", "product_ident", "date_uploaded", "date_submitted", "user_id",
        "product_description", "size_bytes", "is_deleted", "s3_id", "aoi_code",
    },
    "dashboard_job": {
        "job_uuid", "date_created", "date_started", "date_finished", "job_status",
        "product_ident", "skip_steps", "worker_url", "delivery_id", "product_description", "aoi_code",
    },
    "dashboard_s3info": {"id", "host", "access_key", "secret_key", "bucketname", "key_prefix"},
}


def prepare_records(dump, user_ids):
    for table, columns in _COLUMNS.items():
        if table in dump.columns and set(dump.columns[table]) != columns:
            raise ValueError(f"{table}: unsupported source columns")
    storage, deliveries, jobs = [], [], []
    storage_ids, delivery_ids, job_ids = set(), set(), set()
    stats = Counter()
    source_states = Counter()
    for row in dump.tables.get("dashboard_s3info", []):
        location = "dashboard_s3info"
        ident = _unique_id(row["id"], storage_ids, location)
        storage.append(S3Info(
            id=ident,
            host=bounded_text(row["host"], location, 200),
            bucketname=bounded_text(row["bucketname"], location, 100),
            key_prefix=bounded_text(row["key_prefix"], location, 500),
            access_key="", secret_key="",
        ))
    for row in dump.tables["dashboard_delivery"]:
        location = "dashboard_delivery"
        ident = _unique_id(row["id"], delivery_ids, location)
        user_id = _reference(row["user_id"], user_ids, location, nullable=True)
        source_id = _reference(row["s3_id"], storage_ids, location, nullable=True)
        submitted_at = timestamp(row["date_submitted"], location, nullable=True)
        unit = _reported_unit(row["aoi_code"], stats)
        deliveries.append(Delivery(
            id=ident, user_id=user_id, s3_id=source_id,
            filename=bounded_text(row["filename"], location, 500),
            size_bytes=integer(row["size_bytes"], location, min_value=0),
            date_uploaded=timestamp(row["date_uploaded"], location),
            date_submitted=submitted_at,
            product_ident=bounded_text(row["product_ident"], location, 64, nullable=True),
            product_description=bounded_text(row["product_description"], location, 500, nullable=True),
            product_unit_code=unit, submitted_product_unit_code=None,
            is_deleted=boolean(row["is_deleted"], location),
        ))
        stats["submitted_deliveries"] += submitted_at is not None
        stats["deleted_deliveries"] += row["is_deleted"] == "t"
    for row in dump.tables["dashboard_job"]:
        location = "dashboard_job"
        try:
            ident = UUID(row["job_uuid"])
        except (TypeError, ValueError, AttributeError):
            raise ValueError(f"{location}: invalid job UUID") from None
        if ident in job_ids:
            raise ValueError(f"{location}: duplicate job UUID")
        job_ids.add(ident)
        status = bounded_text(row["job_status"], location, 64)
        if status not in {JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL,
                          JOB_RUNNING, JOB_TIMEOUT, JOB_WAITING}:
            raise ValueError(f"{location}: unsupported job status")
        source_states[status] += 1
        if status in (JOB_RUNNING, JOB_WAITING):
            status = JOB_LOST
            stats["unfinished_jobs_disabled"] += 1
        jobs.append(Job(
            job_uuid=ident,
            delivery_id=_reference(row["delivery_id"], delivery_ids, location),
            date_created=timestamp(row["date_created"], location),
            date_started=timestamp(row["date_started"], location, nullable=True),
            date_finished=timestamp(row["date_finished"], location, nullable=True),
            job_status=status,
            product_ident=bounded_text(row["product_ident"], location, 64),
            product_description=bounded_text(row["product_description"], location, 500),
            product_unit_code=_reported_unit(row["aoi_code"], stats),
            submitted_product_unit_code=None,
            skip_steps=bounded_text(row["skip_steps"], location, 100, nullable=True),
            worker_url=bounded_text(row["worker_url"], location, 500, nullable=True),
            request_source="legacy", requested_by=None, requested_by_username="",
            product_release=None, qc_definition=None,
        ))
    stats["deliveries_without_jobs"] = len(delivery_ids - {job.delivery_id for job in jobs})
    return storage, deliveries, jobs, dict(stats), dict(source_states)


def _unique_id(value, seen, location):
    ident = integer(value, location)
    if ident in seen:
        raise ValueError(f"{location}: duplicate ID")
    seen.add(ident)
    return ident


def _reference(value, ids, location, nullable=False):
    if value is None and nullable:
        return None
    ident = integer(value, location)
    if ident not in ids:
        raise ValueError(f"{location}: missing referenced row")
    return ident


def _reported_unit(value, stats):
    normalized = legacy_aoi_to_product_unit_code(value)
    if value is not None and normalized != value:
        stats["reported_unit_values_normalized" if normalized else "invalid_reported_units_left_empty"] += 1
    return normalized
