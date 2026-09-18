"""Opaque business identity metadata, independent of geographic AOI params."""

from qc_tool.product_units import PRODUCT_UNIT_CODE_KEY, normalize_product_unit_code


CONFLICT_KEY = "_product_unit_code_conflict"


def set_product_unit_status_property(status, key, value):
    if key != PRODUCT_UNIT_CODE_KEY:
        return False
    _merge(status.status_properties, status, value)
    return True


def merge_step_product_unit_metadata(job_params, status):
    if PRODUCT_UNIT_CODE_KEY in status.status_properties:
        _merge(job_params, status, status.status_properties[PRODUCT_UNIT_CODE_KEY])


def _merge(previous, status, value):
    canonical = normalize_product_unit_code(value)
    old = normalize_product_unit_code(previous.get(PRODUCT_UNIT_CODE_KEY))
    conflicted = previous.get(CONFLICT_KEY, False) or status.params.get(CONFLICT_KEY, False)
    if conflicted or (old is not None and canonical != old):
        status.status_properties[PRODUCT_UNIT_CODE_KEY] = None
        status.params[CONFLICT_KEY] = True
        message = "Product unit metadata is unavailable because checks reported conflicting identifiers."
        if message not in status.messages:
            status.info(message)
    else:
        # Preserve malformed values as malformed: only explicit null means clear
        # when the frontend projects this retained result document.
        status.status_properties[PRODUCT_UNIT_CODE_KEY] = canonical if canonical is not None else value


def merge_result_metadata(job_result, job_params, status):
    """Publish new metadata without inventing a contradictory legacy null."""

    if (
        PRODUCT_UNIT_CODE_KEY in status.status_properties
        and "aoi_code" not in job_params
        and "aoi_code" not in status.status_properties
    ):
        job_result.pop("aoi_code", None)
    job_result.update(status.status_properties)
