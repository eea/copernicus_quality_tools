"""Publish canonical AOI result metadata without changing QC outcomes."""

from qc_tool.aoi import AOI_CODE_KEY
from qc_tool.aoi import aoi_codes_equivalent
from qc_tool.aoi import is_aoi_input_alias
from qc_tool.aoi import merge_aoi_metadata


AOI_CONFLICT_KEY = "_aoi_code_conflict"


def set_aoi_status_property(status, key, value):
    """Store any supported external AOI alias under the canonical key."""

    if not is_aoi_input_alias(key):
        return False

    merged = merge_aoi_metadata(
        status.status_properties.get(AOI_CODE_KEY),
        value,
        already_conflicted=status.params.get(AOI_CONFLICT_KEY, False),
    )
    status.status_properties[AOI_CODE_KEY] = merged.value
    if merged.conflicted:
        _mark_conflict(status)
    return True


def merge_step_aoi_metadata(job_params, status):
    """Merge one check's AOI property into the job-wide metadata state."""

    if AOI_CODE_KEY not in status.status_properties:
        return

    merged = merge_aoi_metadata(
        job_params.get(AOI_CODE_KEY),
        status.status_properties.get(AOI_CODE_KEY),
        already_conflicted=job_params.get(AOI_CONFLICT_KEY, False),
    )
    status.status_properties[AOI_CODE_KEY] = merged.value
    if merged.conflicted:
        _mark_conflict(status)
        return

    # Product checks may need their original representation (for example,
    # zero-padded identifiers in a boundary filename). Preserve an equivalent
    # raw parameter for downstream checks while publishing only the canonical
    # value in the result metadata.
    previous_raw_aoi = job_params.get(AOI_CODE_KEY)
    if aoi_codes_equivalent(previous_raw_aoi, merged.value):
        status.params[AOI_CODE_KEY] = previous_raw_aoi
        return
    if AOI_CODE_KEY not in status.params:
        status.params[AOI_CODE_KEY] = merged.value
        return

    raw_aoi_code = status.params[AOI_CODE_KEY]
    if raw_aoi_code is None and merged.value is None:
        return
    if not aoi_codes_equivalent(raw_aoi_code, merged.value):
        _mark_conflict(status)


def invalidate_aoi_metadata(status):
    """Clear AOI metadata after an existing naming validation failure."""

    status.status_properties[AOI_CODE_KEY] = None
    status.params[AOI_CODE_KEY] = None
    status.params[AOI_CONFLICT_KEY] = True


def _mark_conflict(status):
    status.status_properties[AOI_CODE_KEY] = None
    status.params[AOI_CODE_KEY] = None
    status.params[AOI_CONFLICT_KEY] = True
    message = (
        "AOI metadata is unavailable because the job reported conflicting "
        "identifiers."
    )
    if message not in status.messages:
        status.info(message)
