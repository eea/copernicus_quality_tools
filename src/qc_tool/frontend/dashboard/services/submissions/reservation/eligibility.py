"""Fail-closed delivery, job, product unit, and catalog submission eligibility."""

import re

from qc_tool.product_units import normalize_product_unit_code
from qc_tool.common import JOB_OK
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import ProductRelease

from ..errors import SubmissionError


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_delivery(delivery, *, request_channel):
    if delivery.is_deleted:
        raise SubmissionError(
            "delivery_deleted",
            "A deleted delivery cannot be submitted.",
            409,
        )
    if delivery.date_submitted is not None:
        raise SubmissionError(
            "submission_receipt_unavailable",
            "This delivery is already recorded as submitted, but its publication "
            "receipt is unavailable. It cannot be submitted again.",
            409,
        )
    if delivery.user_id is None or delivery.user is None:
        raise SubmissionError(
            "delivery_owner_unavailable",
            "The delivery owner is unavailable.",
            409,
        )
    if request_channel not in DeliverySubmission.RequestChannel.values:
        raise SubmissionError(
            "invalid_submission_channel",
            "The submission request channel is invalid.",
            400,
        )


def latest_successful_job(delivery):
    latest_job = (
        Job.objects.select_for_update(of=("self",))
        .filter(delivery=delivery)
        .select_related("product_release", "qc_definition")
        .order_by("-date_created", "-job_uuid")
        .first()
    )
    if latest_job is None:
        raise SubmissionError(
            "qc_job_required",
            "Run quality control before submitting this delivery.",
            409,
        )
    if latest_job.job_status != JOB_OK:
        raise SubmissionError(
            "latest_qc_not_successful",
            "The latest QC job must finish successfully before submission.",
            409,
        )
    return latest_job


def validated_submitted_product_unit(delivery, latest_job):
    submitted_unit = normalize_product_unit_code(latest_job.verified_product_unit_code)
    if submitted_unit is None:
        raise SubmissionError(
            "product_unit_unavailable",
            "The successful QC job did not verify exactly one product unit.",
            409,
        )
    delivery_unit = normalize_product_unit_code(delivery.verified_product_unit_code)
    if delivery_unit is not None and delivery_unit != submitted_unit:
        raise SubmissionError(
            "delivery_product_unit_mismatch",
            "The latest QC result conflicts with the product unit already verified "
            "for this ZIP.",
            409,
        )
    return submitted_unit


def validated_input_digest(latest_job):
    """Return the checksum binding publication to the exact QC input."""

    value = latest_job.input_sha256
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(
        value.casefold()
    ):
        raise SubmissionError(
            "input_digest_unavailable",
            "The successful QC job did not record a valid input checksum. "
            "Run quality control again before submitting this delivery.",
            409,
        )
    return value.casefold()


def catalog_target(latest_job, submitted_unit):
    release = latest_job.product_release
    if release is None or latest_job.qc_definition_id is None:
        raise SubmissionError(
            "catalog_release_unavailable",
            "The QC job is not associated with an authoritative product "
            "release. Ask an administrator to approve its delivery plan, then run QC again.",
            409,
        )
    if not release.product.is_active:
        raise SubmissionError("product_inactive", "This product has been removed from active use.", 409)
    # A plan-only revision may approve an already checked definition. Preserve
    # the job's original provenance while targeting the current plan of the
    # same stream, only when its exact definition still belongs to that plan.
    current = ProductRelease.objects.filter(
        release_key=release.release_key, is_current=True,
        definition_links__qc_definition_id=latest_job.qc_definition_id,
    ).first()
    if current is None:
        raise SubmissionError(
            "qc_definition_outdated",
            "The product specification has changed. Run QC with its current specification before submitting.", 409,
        )
    release = current
    if release.coverage_state != ProductRelease.CoverageState.AUTHORITATIVE:
        raise SubmissionError(
            "catalog_release_not_authoritative",
            "An administrator must approve the product's delivery plan before submissions can be sent for review.",
            409,
        )
    if not release.definition_links.filter(
        qc_definition_id=latest_job.qc_definition_id
    ).exists():
        raise SubmissionError(
            "qc_definition_release_mismatch",
            "The QC definition does not belong to the job's product release.",
            409,
        )
    try:
        product_unit = ProductUnit.objects.get(
            product_release=release,
            product_unit_code=submitted_unit,
        )
    except ProductUnit.DoesNotExist as exc:
        raise SubmissionError(
            "submitted_product_unit_not_expected",
            "The product unit verified in the ZIP is not expected by this product "
            "release.",
            409,
        ) from exc
    return release, product_unit
