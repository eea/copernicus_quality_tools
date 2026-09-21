"""Queryable result facts used by publication and report fallback.

The complete result and its software version remain in the original job
artifacts, which publication retains and checksums. Do not duplicate that
document in the execution table.
"""


def apply_result_metadata(job, job_result):
    """Project only fields that have a database consumer."""
    values = {
        "input_sha256": _bounded_text(job_result.get("hash"), 64),
        "reference_period": _bounded_text(
            job_result.get("reference_year"),
            32,
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
