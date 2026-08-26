"""Maintain the denormalized AOI/product projection on Delivery."""

from qc_tool.aoi import normalize_aoi_code


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
            "aoi_code",
            "aoi_code_submitted",
            "product_ident",
            "product_description",
        )
        .first()
    )

    updated_fields = []
    aoi_code = (
        normalize_aoi_code(latest_job.aoi_code)
        if latest_job is not None
        else None
    )
    if delivery.aoi_code != aoi_code:
        delivery.aoi_code = aoi_code
        updated_fields.append("aoi_code")

    # The explicit submitted AOI is the identity verified from this one-ZIP,
    # one-AOI upload.  Preserve it while a newer job is waiting and reject
    # conflicting terminal observations in the lifecycle service.
    submitted_aoi = delivery.aoi_code_submitted
    if (
        submitted_aoi is None
        and latest_job is not None
        and latest_job.aoi_code_submitted
    ):
        submitted_aoi = normalize_aoi_code(latest_job.aoi_code_submitted)
    if delivery.aoi_code_submitted != submitted_aoi:
        delivery.aoi_code_submitted = submitted_aoi
        updated_fields.append("aoi_code_submitted")

    if latest_job is not None:
        for field_name in ("product_ident", "product_description"):
            value = getattr(latest_job, field_name)
            if getattr(delivery, field_name) != value:
                setattr(delivery, field_name, value)
                updated_fields.append(field_name)

    if updated_fields:
        delivery.save(update_fields=updated_fields)
    return updated_fields
