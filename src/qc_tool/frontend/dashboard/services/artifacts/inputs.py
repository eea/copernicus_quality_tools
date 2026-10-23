"""Resolve the exact retained ZIP checked by one historical QC job."""

import hashlib
import json
from pathlib import PurePosixPath
import re

from django.conf import settings

from qc_tool.common import CONFIG, JOB_INPUT_DIRNAME
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.services.submissions.artifacts import open_submission_file, _real_directory
from qc_tool.frontend.dashboard.services.submissions.publication.identity import verify_manifest_identity
from qc_tool.frontend.dashboard.services.submissions.publication.integrity import _expected_inventory
from qc_tool.frontend.dashboard.services.submissions.publication.manifest import MANIFEST_FILENAME, MAX_MANIFEST_BYTES
from qc_tool.frontend.dashboard.services.submissions.storage import artifact_directory
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError, resolve_user_delivery_upload

from .errors import ArtifactUnavailable
from .files import open_regular_artifact


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNAVAILABLE = (ArtifactUnavailable, DeliveryUploadPathError, OSError, ValueError)


def _expected_digest(job):
    digest = job.input_sha256
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ArtifactUnavailable("This historical QC run has no verified input checksum.")
    return digest


def _publication_input(job, expected):
    """Read original evidence after separately checking the local FK context."""

    from qc_tool.database.transfers.provenance import publication_identity

    submission = DeliverySubmission.objects.select_related("product_unit").filter(
        job_id=job.pk, publication_state=DeliverySubmission.PublicationState.PUBLISHED,
    ).first()
    if submission is None or not CONFIG.get("submission_dir"):
        raise ArtifactUnavailable
    if (
        submission.job_id != job.pk or submission.delivery_id != job.delivery_id
        or not job.product_release_id or submission.product_release_id != job.product_release_id
        or submission.product_unit.product_release_id != submission.product_release_id
        or submission.product_unit_code != submission.product_unit.product_unit_code
        or submission.verified_product_unit_code != submission.product_unit_code
        or job.verified_product_unit_code != submission.verified_product_unit_code
        or submission.input_digest != expected
    ):
        raise ArtifactUnavailable
    identity = {
        "submission_uuid": str(submission.pk), "delivery_id": submission.delivery_id,
        "job_id": str(submission.job_id), "product_release_id": submission.product_release_id,
        "product_unit_id": submission.product_unit_id, "product_unit_code": submission.product_unit_code,
        "verified_product_unit_code": submission.verified_product_unit_code,
        "input_digest": submission.input_digest, "requested_at": submission.requested_at.isoformat(),
        "artifact_digest": submission.artifact_digest,
    }
    identity.update(publication_identity(submission) or {})
    # UUIDs and input hashes are stable identities, never remapping decisions.
    if (str(identity.get("job_id")) != str(job.pk)
            or str(identity.get("submission_uuid")) != str(submission.pk)
            or identity.get("input_digest") != expected
            or identity.get("artifact_digest") != submission.artifact_digest):
        raise ArtifactUnavailable
    root = artifact_directory(CONFIG["submission_dir"], submission.artifact_key)
    with open_regular_artifact(root, MANIFEST_FILENAME) as stream:
        payload = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ArtifactUnavailable
    manifest = json.loads(payload)
    verify_manifest_identity(manifest, identity)
    inventory = _expected_inventory(manifest, MANIFEST_FILENAME)
    inputs = [name for name in inventory if name.startswith(JOB_INPUT_DIRNAME + "/")]
    if len(inputs) != 1:
        raise ArtifactUnavailable
    filename = inputs[0]
    parts = PurePosixPath(filename).parts
    if len(parts) != 2 or not parts[-1].lower().endswith(".zip") or inventory[filename] != (expected, job.delivery.size_bytes):
        raise ArtifactUnavailable
    return submission, filename, root


def _current_upload(job):
    return _open_upload(job.delivery)


def _open_upload(delivery):
    if delivery.is_deleted or delivery.s3_id is not None or delivery.user_id is None:
        raise ArtifactUnavailable
    path = resolve_user_delivery_upload(
        delivery.filename, media_root=settings.MEDIA_ROOT, username=delivery.user.username,
    )
    return open_regular_artifact(path.parent, path.name)


def _verified_stream(stream, digest, size):
    try:
        actual, length = hashlib.sha256(), 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            actual.update(block)
            length += len(block)
        if length != size or actual.hexdigest() != digest:
            raise ArtifactUnavailable
        stream.seek(0)
        return stream
    except Exception:
        stream.close()
        raise


def open_delivery_input(delivery):
    """Open a current upload, enforcing its recorded checksum when available.

    Historical jobs always require their own recorded digest. Legacy current
    deliveries without a checksum retain their existing download behavior.
    """

    expected = delivery.content_sha256
    if expected and (not isinstance(expected, str) or not _SHA256.fullmatch(expected)):
        raise ArtifactUnavailable
    if not expected:
        from qc_tool.database.transfers.artifact_references import imported_delivery_requires_verification
        if imported_delivery_requires_verification(delivery):
            raise ArtifactUnavailable("This imported input has no verified original checksum; its history is retained.")
    try:
        stream = _open_upload(delivery)
        return _verified_stream(stream, expected, delivery.size_bytes) if expected else stream
    except _UNAVAILABLE as exc:
        raise ArtifactUnavailable("The ZIP is unavailable or differs from its recorded checksum.") from exc


def open_job_input(job):
    """Return an open, checksummed input descriptor for an already authorized job.

    Never infer historical input from a filename. A deleted delivery can still
    have a verified immutable publication; its current upload is not a fallback.
    """

    expected = _expected_digest(job)
    try:
        submission, filename, _root = _publication_input(job, expected)
        return open_submission_file(submission, filename)
    except _UNAVAILABLE:
        pass
    try:
        return _verified_stream(_current_upload(job), expected, job.delivery.size_bytes)
    except _UNAVAILABLE as exc:
        raise ArtifactUnavailable("The original ZIP is unavailable or differs from this QC run's checksum.") from exc


def job_input_availability(job):
    """Present source availability without hashing a large ZIP on every page.

    The download always hashes the same descriptor it serves. Availability is
    deliberately not presented as a completed byte-integrity verification.
    """

    try:
        expected = _expected_digest(job)
    except ArtifactUnavailable:
        return {"available": False, "message": "This historical run has no recorded input checksum."}
    try:
        _submission, filename, root = _publication_input(job, expected)
        parts = PurePosixPath(filename).parts
        with open_regular_artifact(_real_directory(root, parts[:-1]), parts[-1]):
            pass
        return {"available": True, "message": "Retained submission input; checksum verified when downloaded."}
    except _UNAVAILABLE:
        pass
    try:
        with _current_upload(job):
            pass
        return {"available": True, "message": "The ZIP checksum is verified against this run when downloaded."}
    except _UNAVAILABLE:
        return {"available": False, "message": "The original ZIP is not available in retained storage."}
