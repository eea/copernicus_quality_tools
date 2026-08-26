"""Translate untrusted worker result metadata into a typed DB update."""

from qc_tool.aoi import normalize_aoi_code

from .contracts import AoiResultUpdate
from .contracts import AoiUpdateAction


def aoi_update_from_result(job_result):
    """Return the tri-state AOI update represented by one result document.

    Missing or malformed metadata preserves the database value. Explicit
    ``null`` clears it. A valid string is normalized before it can be stored.
    """

    if not isinstance(job_result, dict) or "aoi_code" not in job_result:
        return AoiResultUpdate(AoiUpdateAction.PRESERVE)

    raw_value = job_result["aoi_code"]
    if raw_value is None:
        return AoiResultUpdate(AoiUpdateAction.CLEAR)

    value = normalize_aoi_code(raw_value)
    if value is None:
        return AoiResultUpdate(AoiUpdateAction.PRESERVE)
    return AoiResultUpdate(AoiUpdateAction.SET, value=value)


def apply_result_aoi(job, job_result):
    """Dual-write legacy and explicit submitted-AOI job fields."""

    update = aoi_update_from_result(job_result)
    if update.action is AoiUpdateAction.PRESERVE:
        return []
    if update.action is AoiUpdateAction.CLEAR:
        value = None
    else:
        value = update.value
    changed = []
    for field_name in ("aoi_code", "aoi_code_submitted"):
        if getattr(job, field_name) != value:
            setattr(job, field_name, value)
            changed.append(field_name)
    return changed
