"""Verify original publication identity without rewriting immutable manifests."""

from datetime import datetime
import hashlib
import json


def verify_manifest_identity(manifest, submission):
    """Match a manifest against its original, possibly mapped source identity.

    ``submission`` is a JSON-safe receipt projection. An additive import may
    map local integer keys; its reviewed provenance supplies the original keys
    here. The original manifest and its digest always remain unchanged.
    """

    if not isinstance(manifest, dict):
        raise ValueError("A publication manifest is invalid.")
    body = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    digest = hashlib.sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    version = manifest.get("schema_version")
    unit, code, verified_code = (
        ("product_aoi_id", "aoi_code", "aoi_code_submitted")
        if version == 1 else
        ("product_unit_id", "product_unit_code", "submitted_product_unit_code")
    )
    foreign_keys = (
        ("product_unit_id", "product_unit_code", "submitted_product_unit_code")
        if version == 1 else ("product_aoi_id", "aoi_code", "aoi_code_submitted")
    )
    try:
        expected = {
            "submission_id": str(submission["submission_uuid"]),
            "delivery_id": submission["delivery_id"],
            "job_id": str(submission["job_id"]),
            "product_release_id": submission["product_release_id"],
            unit: submission["product_unit_id"],
            code: submission["product_unit_code"],
            verified_code: submission["verified_product_unit_code"],
            "input_sha256": submission["input_digest"],
        }
        same_time = datetime.fromisoformat(manifest["requested_at"].replace("Z", "+00:00")) == datetime.fromisoformat(
            submission["requested_at"].replace("Z", "+00:00"),
        )
        matches = (
            type(version) is int and version in (1, 2)
            and digest == submission["artifact_digest"] == manifest.get("artifact_sha256")
            and same_time and manifest.get("storage") == "local"
            and not any(key in manifest for key in foreign_keys)
            and all(manifest.get(key) == value for key, value in expected.items())
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("A publication manifest differs from its database receipt.") from exc
    if not matches:
        raise ValueError("A publication manifest differs from its database receipt.")
