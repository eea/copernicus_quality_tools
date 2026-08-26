"""Row-locked QC job creation and delivery projection refresh."""

from django.db import transaction
from django.utils import timezone

from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING

from ..projections import sync_locked_delivery_from_latest_job


def create_delivery_job(
    delivery,
    *,
    product_ident,
    product_description,
    skip_steps,
    requested_by=None,
    request_source="legacy",
    api_token=None,
    account_access=None,
    logger,
):
    """Create a job and reset/project the delivery under one row lock."""

    Delivery = delivery._meta.model
    Job = delivery._meta.apps.get_model("dashboard", "Job")
    with transaction.atomic():
        locked_delivery = Delivery.objects.select_for_update().get(
            pk=delivery.pk
        )
        _require_job_creation_allowed(
            locked_delivery,
            Job,
            account_access=account_access,
        )
        qc_definition, product_release = _catalog_snapshot(
            product_ident,
            logger=logger,
        )
        job = Job.objects.create(
            date_created=timezone.now(),
            job_status=JOB_WAITING,
            product_ident=product_ident,
            product_description=product_description,
            skip_steps=skip_steps,
            delivery=locked_delivery,
            requested_by=requested_by,
            requested_by_username=_actor_username(requested_by),
            request_source=request_source,
            requested_api_token_id=(
                getattr(api_token, "pk", None) if api_token is not None else None
            ),
            requested_api_token_name=(
                getattr(api_token, "name", "") if api_token is not None else ""
            ),
            qc_definition=qc_definition,
            product_release=product_release,
        )
        sync_locked_delivery_from_latest_job(locked_delivery)

    _copy_projection(locked_delivery, delivery)
    return job


def refresh_delivery_projection(delivery):
    """Safely refresh one delivery from its deterministic latest job."""

    Delivery = delivery._meta.model
    with transaction.atomic():
        locked_delivery = Delivery.objects.select_for_update().get(
            pk=delivery.pk
        )
        updated_fields = sync_locked_delivery_from_latest_job(locked_delivery)
    _copy_projection(locked_delivery, delivery)
    return updated_fields


def _require_job_creation_allowed(delivery, Job, *, account_access):
    if delivery.is_deleted:
        raise ValueError("A deleted delivery cannot start a QC job.")
    if account_access is not None and not account_access.can_manage_user(
        delivery.user_id
    ):
        raise PermissionError(
            "The account cannot create a QC job for this delivery."
        )
    if delivery.date_submitted is not None:
        raise ValueError("A submitted delivery cannot start a QC job.")
    if hasattr(delivery, "submission"):
        raise ValueError("A reserved delivery cannot start a QC job.")
    if Job.objects.filter(
        delivery=delivery,
        job_status__in=(JOB_WAITING, JOB_RUNNING),
    ).exists():
        raise ValueError("The delivery already has an active QC job.")


def _catalog_snapshot(product_ident, *, logger):
    from qc_tool.frontend.dashboard.services.catalog import CatalogError
    from qc_tool.frontend.dashboard.services.catalog import (
        snapshot_definition_for_job,
    )

    try:
        return snapshot_definition_for_job(product_ident)
    except CatalogError:
        # Compatibility for deployments not yet synchronized. Submission is
        # still fail-closed because it requires an authoritative release/AOI.
        logger.warning(
            "QC definition %s could not be snapshotted for the job.",
            product_ident,
        )
        return None, None


def _actor_username(actor):
    if actor is None:
        return ""
    getter = getattr(actor, "get_username", None)
    return str(getter() if callable(getter) else getattr(actor, "username", ""))[
        :150
    ]


def _copy_projection(source, destination):
    for field_name in (
        "product_ident",
        "product_description",
        "aoi_code",
        "aoi_code_submitted",
    ):
        setattr(destination, field_name, getattr(source, field_name))
