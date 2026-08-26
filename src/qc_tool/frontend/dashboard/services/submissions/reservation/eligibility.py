"""Fail-closed delivery, job, AOI, and catalog submission eligibility."""

import re

from qc_tool.aoi import normalize_aoi_code
from qc_tool.common import JOB_OK
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import ProductAOI
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
            "legacy_submission_requires_reconciliation",
            "This delivery was submitted by the legacy workflow and must be "
            "reconciled before it can use the new publication lifecycle.",
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


def validated_submitted_aoi(delivery, latest_job):
    submitted_aoi = normalize_aoi_code(latest_job.aoi_code_submitted)
    if submitted_aoi is None:
        raise SubmissionError(
            "aoi_unavailable",
            "The successful QC job did not verify exactly one AOI.",
            409,
        )
    delivery_aoi = normalize_aoi_code(delivery.aoi_code_submitted)
    if delivery_aoi is not None and delivery_aoi != submitted_aoi:
        raise SubmissionError(
            "delivery_aoi_mismatch",
            "The latest QC result conflicts with the AOI already verified "
            "for this ZIP.",
            409,
        )
    return submitted_aoi


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


def catalog_target(latest_job, submitted_aoi):
    release = latest_job.product_release
    if release is None or latest_job.qc_definition_id is None:
        raise SubmissionError(
            "catalog_release_unavailable",
            "The QC job is not associated with an authoritative product "
            "release. Synchronize the catalog and run QC again.",
            409,
        )
    if release.coverage_state != ProductRelease.CoverageState.AUTHORITATIVE:
        raise SubmissionError(
            "catalog_release_not_authoritative",
            "The QC job's product release does not have authoritative AOI "
            "coverage.",
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
        product_aoi = ProductAOI.objects.get(
            product_release=release,
            aoi_code=submitted_aoi,
        )
    except ProductAOI.DoesNotExist as exc:
        raise SubmissionError(
            "submitted_aoi_not_expected",
            "The AOI verified in the ZIP is not expected by this product "
            "release.",
            409,
        ) from exc
    return release, product_aoi
