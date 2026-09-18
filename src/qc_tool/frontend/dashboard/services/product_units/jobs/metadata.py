"""Bounded, queryable metadata snapshots from one worker result."""

import hashlib
import json

from django.utils import timezone


def apply_result_metadata(job, job_result):
    """Persist queryable result facts and a JSON audit snapshot."""

    canonical = json.dumps(
        job_result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    values = {
        "result_metadata": job_result,
        "result_sha256": hashlib.sha256(canonical).hexdigest(),
        "result_received_at": timezone.now(),
        "input_sha256": _bounded_text(job_result.get("hash"), 64),
        "reference_period": _bounded_text(
            job_result.get("reference_year"),
            32,
        ),
        "qc_tool_version": _bounded_text(
            job_result.get("qc_tool_version"),
            128,
        ),
    }
    changed = []
    for field_name, value in values.items():
        if getattr(job, field_name) != value:
            setattr(job, field_name, value)
            changed.append(field_name)
    return changed


def _bounded_text(value, maximum):
    if value is None:
        return ""
    return str(value)[:maximum]
