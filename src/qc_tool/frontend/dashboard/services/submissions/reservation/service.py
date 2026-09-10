"""Row-locked creation of one durable submission reservation."""

from django.db import transaction

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.services.catalog.sync.locks import lock_catalog_sync

from ..errors import SubmissionError
from .eligibility import catalog_target
from .eligibility import latest_successful_job
from .eligibility import validate_delivery
from .eligibility import validated_input_digest
from .eligibility import validated_submitted_aoi
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
    if not account_access.can_manage_user(delivery.user_id):
        raise SubmissionError(
            "object_permission_denied",
            "The account cannot submit this delivery.",
            403,
        )

    existing = _existing_submission(delivery)
    if existing is not None:
        return reserved_contract(existing, already_existed=True)

    validate_delivery(delivery, request_channel=request_channel)
    latest_job = latest_successful_job(delivery)
    submitted_aoi = validated_submitted_aoi(delivery, latest_job)
    input_digest = validated_input_digest(latest_job)
    release, product_aoi = catalog_target(latest_job, submitted_aoi)
    _persist_delivery_identity(delivery, submitted_aoi)

    submission = DeliverySubmission.objects.create(
        delivery=delivery,
        job=latest_job,
        product_release=release,
        product_aoi=product_aoi,
        aoi_code=product_aoi.aoi_code,
        aoi_code_submitted=submitted_aoi,
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
            "product_aoi",
        )
        .filter(delivery=delivery)
        .first()
    )


def _persist_delivery_identity(delivery, submitted_aoi):
    if delivery.aoi_code_submitted != submitted_aoi:
        delivery.aoi_code_submitted = submitted_aoi
        delivery.save(update_fields=("aoi_code_submitted",))
