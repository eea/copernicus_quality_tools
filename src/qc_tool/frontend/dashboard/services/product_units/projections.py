"""Maintain the denormalized product unit/product projection on Delivery."""

from qc_tool.product_units import normalize_product_unit_code


def sync_locked_delivery_from_latest_job(delivery):
    """Project deterministic latest-job metadata onto a locked delivery.

    The caller must hold a database row lock for ``delivery``. The explicit
    name makes that concurrency contract difficult to overlook. This service
    is intentionally the only place that defines the projection ordering.
    """

    Job = delivery._meta.apps.get_model("dashboard", "Job")
    latest_job = (
        Job.objects.filter(delivery_id=delivery.pk)
        .order_by("-date_created", "-job_uuid")
        .only(
            "product_unit_code",
            "verified_product_unit_code",
            "product_ident",
            "product_description",
        )
        .first()
    )

    updated_fields = []
    product_unit_code = (
        normalize_product_unit_code(latest_job.product_unit_code)
        if latest_job is not None
        else None
    )
    if delivery.product_unit_code != product_unit_code:
        delivery.product_unit_code = product_unit_code
        updated_fields.append("product_unit_code")

    # The verified product unit is the identity established from this one-ZIP,
    # one-product unit upload.  Preserve it while a newer job is waiting and reject
    # conflicting terminal observations in the lifecycle service.
    submitted_unit = delivery.verified_product_unit_code
    if (
        submitted_unit is None
        and latest_job is not None
        and latest_job.verified_product_unit_code
    ):
        submitted_unit = normalize_product_unit_code(latest_job.verified_product_unit_code)
    if delivery.verified_product_unit_code != submitted_unit:
        delivery.verified_product_unit_code = submitted_unit
        updated_fields.append("verified_product_unit_code")

    if latest_job is not None:
        for field_name in ("product_ident", "product_description"):
            value = getattr(latest_job, field_name)
            if getattr(delivery, field_name) != value:
                setattr(delivery, field_name, value)
                updated_fields.append(field_name)

    if updated_fields:
        delivery.save(update_fields=updated_fields)
    return updated_fields
