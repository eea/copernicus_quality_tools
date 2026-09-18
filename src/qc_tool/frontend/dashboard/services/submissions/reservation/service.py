"""Row-locked creation of one durable submission reservation."""

from django.db import transaction

from qc_tool.frontend.dashboard.access.deliveries import can_manage_delivery
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.services.catalog.sync.locks import lock_catalog_sync

from ..errors import SubmissionError
from .eligibility import catalog_target
from .eligibility import latest_successful_job
from .eligibility import validate_delivery
from .eligibility import validated_input_digest
from .eligibility import validated_submitted_product_unit
from .mapping import actor_username
from .mapping import reserved_contract


@transaction.atomic
def reserve_submission(
    *,
    delivery_id,
    actor,
    account_access,
    request_channel,
    api_token,
):
    """Lock a delivery and reserve its one durable submission record."""

    lock_catalog_sync()
    delivery = _locked_delivery(delivery_id)
    if not (
        account_access.can_submit
        and can_manage_delivery(account_access, delivery)
    ):
        raise SubmissionError(
            "object_permission_denied",
            "The account cannot submit this delivery.",
            403,
        )

    existing = _existing_submission(delivery)
    if existing is not None:
        _require_submission_product(account_access, existing.job, existing.product_release)
        return reserved_contract(existing, already_existed=True)

    validate_delivery(delivery, request_channel=request_channel)
    latest_job = latest_successful_job(delivery)
    _require_submission_product(account_access, latest_job, latest_job.product_release)
    submitted_unit = validated_submitted_product_unit(delivery, latest_job)
    input_digest = validated_input_digest(latest_job)
    release, product_unit = catalog_target(latest_job, submitted_unit)
    _require_submission_product(account_access, latest_job, release)
    _persist_delivery_identity(delivery, submitted_unit)

    submission = DeliverySubmission.objects.create(
        delivery=delivery,
        job=latest_job,
        product_release=release,
        product_unit=product_unit,
        product_unit_code=product_unit.product_unit_code,
        submitted_product_unit_code=submitted_unit,
        submitted_by=actor if getattr(actor, "pk", None) else None,
        submitted_by_username=actor_username(actor),
        request_channel=request_channel,
        api_token_id=(
            getattr(api_token, "pk", None) if api_token is not None else None
        ),
        api_token_name=(getattr(api_token, "name", "") if api_token else ""),
        input_digest=input_digest,
    )
    return reserved_contract(submission, already_existed=False)


def _require_submission_product(account_access, job, release):
    if account_access.can_access_product_snapshot(
        job.product_ident, release.product.ident if release is not None else None,
    ):
        return
    raise SubmissionError(
        "object_permission_denied", "The account is not assigned to this product.", 403,
    )


def _locked_delivery(delivery_id):
    try:
        return Delivery.objects.select_for_update(of=("self",)).get(
            pk=delivery_id
        )
    except Delivery.DoesNotExist as exc:
        raise SubmissionError(
            "delivery_not_found",
            "The delivery does not exist.",
            404,
        ) from exc


def _existing_submission(delivery):
    return (
        DeliverySubmission.objects.select_for_update(of=("self",))
        .select_related(
            "delivery__user",
            "job",
            "product_release",
            "product_unit",
        )
        .filter(delivery=delivery)
        .first()
    )


def _persist_delivery_identity(delivery, submitted_unit):
    if delivery.submitted_product_unit_code != submitted_unit:
        delivery.submitted_product_unit_code = submitted_unit
        delivery.save(update_fields=("submitted_product_unit_code",))
