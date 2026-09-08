"""Canonical publication manifests and idempotent recovery validation."""

import hashlib
import json
import re

from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_regular_artifact

from ..contracts import PublicationReceipt
from ..errors import PublicationError
from .integrity import PublicationIntegrityError
from .integrity import verify_publication_inventory
from .secure_copy import sync_directory


MANIFEST_FILENAME = "submission-manifest.json"
SUBMITTED_MARKER = "SUBMITTED"
MANIFEST_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_manifest(reserved, *, input_digest, file_inventory):
    """Return canonical manifest bytes and the digest of its unsigned body."""

    body = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "submission_id": str(reserved.submission_uuid),
        "delivery_id": reserved.delivery_id,
        "job_id": str(reserved.job_uuid),
        "product_release_id": reserved.product_release_id,
        "product_aoi_id": reserved.product_aoi_id,
        "aoi_code": reserved.aoi_code,
        "aoi_code_submitted": reserved.aoi_code_submitted,
        "input_sha256": input_digest,
        "storage": "s3" if reserved.is_s3 else "local",
        "requested_at": reserved.requested_at_iso,
        "files": sorted(file_inventory, key=lambda item: item["path"]),
    }
    digest = _canonical_digest(body)
    return _canonical_json({**body, "artifact_sha256": digest}), digest


def receipt_from_existing(final_directory, reserved):
    """Validate deterministic existing output before treating retry as success."""

    if final_directory.is_symlink() or not final_directory.is_dir():
        raise PublicationError(
            "publication_path_conflict",
            "The deterministic publication path is occupied by unsafe data.",
            409,
        )
    try:
        with open_regular_artifact(
            final_directory,
            MANIFEST_FILENAME,
        ) as artifact:
            payload = artifact.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError
        manifest = json.loads(payload.decode("utf-8"))
    except (
        ArtifactUnavailable,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise PublicationError(
            "publication_manifest_mismatch",
            "The existing publication does not match this submission.",
            409,
        ) from exc

    expected_identity = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "submission_id": str(reserved.submission_uuid),
        "delivery_id": reserved.delivery_id,
        "job_id": str(reserved.job_uuid),
        "product_release_id": reserved.product_release_id,
        "product_aoi_id": reserved.product_aoi_id,
        "aoi_code": reserved.aoi_code,
        "aoi_code_submitted": reserved.aoi_code_submitted,
        "input_sha256": reserved.expected_input_digest,
        "storage": "s3" if reserved.is_s3 else "local",
        "requested_at": reserved.requested_at_iso,
    }
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in expected_identity.items()
    ):
        raise PublicationError(
            "publication_manifest_mismatch",
            "The existing publication does not match this submission.",
            409,
        )

    stated_digest = manifest.get("artifact_sha256")
    body = dict(manifest)
    body.pop("artifact_sha256", None)
    if (
        not isinstance(stated_digest, str)
        or not _SHA256_RE.fullmatch(stated_digest)
        or _canonical_digest(body) != stated_digest
    ):
        raise PublicationError(
            "publication_manifest_mismatch",
            "The existing publication manifest failed integrity validation.",
            409,
        )
    try:
        verify_publication_inventory(
            final_directory,
            manifest,
            manifest_filename=MANIFEST_FILENAME,
            required_paths=(SUBMITTED_MARKER,),
        )
    except PublicationIntegrityError as exc:
        raise PublicationError(
            "publication_manifest_mismatch",
            "The existing publication files failed integrity validation.",
            409,
        ) from exc
    input_digest = manifest.get("input_sha256", "")
    if not isinstance(input_digest, str):
        input_digest = ""
    # Recovery may follow a failure between rename and the parent-directory
    # sync. Do not commit the database receipt until that entry is durable.
    sync_directory(final_directory.parent)
    return PublicationReceipt(
        artifact_path=str(final_directory),
        artifact_digest=stated_digest,
        input_digest=input_digest,
        recovered_existing=True,
    )


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_digest(value):
    return hashlib.sha256(_canonical_json(value)).hexdigest()
