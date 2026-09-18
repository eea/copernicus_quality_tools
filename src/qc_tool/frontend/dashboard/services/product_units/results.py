"""Translate untrusted worker result metadata into a typed DB update."""

from qc_tool.product_units import legacy_aoi_to_product_unit_code, normalize_product_unit_code

from .contracts import ProductUnitResultUpdate
from .contracts import ProductUnitUpdateAction


def product_unit_update_from_result(job_result):
    """Return the tri-state product unit update represented by one result document.

    Missing or malformed metadata preserves the database value. Explicit
    ``null`` clears it. A valid string is normalized before it can be stored.
    """

    if not isinstance(job_result, dict):
        return ProductUnitResultUpdate(ProductUnitUpdateAction.PRESERVE)
    explicit = "product_unit_code" in job_result
    legacy = "aoi_code" in job_result
    if not explicit and not legacy:
        return ProductUnitResultUpdate(ProductUnitUpdateAction.PRESERVE)
    raw_value = job_result["product_unit_code" if explicit else "aoi_code"]
    normalize = normalize_product_unit_code if explicit else legacy_aoi_to_product_unit_code
    if explicit and legacy:
        legacy_raw = job_result["aoi_code"]
        value = normalize_product_unit_code(raw_value)
        legacy_value = legacy_aoi_to_product_unit_code(legacy_raw)
        if not (
            raw_value is None and legacy_raw is None
            or value is not None and legacy_value is not None and value == legacy_value
        ):
            return ProductUnitResultUpdate(ProductUnitUpdateAction.PRESERVE, conflicted=True)
    if raw_value is None:
        return ProductUnitResultUpdate(ProductUnitUpdateAction.CLEAR)

    value = normalize(raw_value)
    if value is None:
        return ProductUnitResultUpdate(ProductUnitUpdateAction.PRESERVE)
    return ProductUnitResultUpdate(ProductUnitUpdateAction.SET, value=value)


def apply_result_product_unit(job, job_result):
    """Project a worker observation without rewriting its retained result."""

    update = product_unit_update_from_result(job_result)
    if update.action is ProductUnitUpdateAction.PRESERVE:
        return []
    if update.action is ProductUnitUpdateAction.CLEAR:
        value = None
    else:
        value = update.value
    changed = []
    for field_name in ("product_unit_code", "submitted_product_unit_code"):
        if getattr(job, field_name) != value:
            setattr(job, field_name, value)
            changed.append(field_name)
    return changed
