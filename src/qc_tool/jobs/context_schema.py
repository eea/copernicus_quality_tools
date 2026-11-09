"""Admission contract for explicit run provenance, never inferred for old jobs."""

from datetime import datetime
import re

from .errors import JobStorageError
from .identifiers import normalize_job_uuid
from .paths import CURRENT_LAYOUT_VERSION, safe_artifact_name


CONTEXT_FORMAT = "qc-tool-job"
CONTEXT_SCHEMA_VERSION = 1
MAX_CONTEXT_BYTES = 64 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SECTIONS = {
    "input": {"filename", "source", "sha256", "hash_files", "reported_hash"},
    "specification": {"filename", "sha256"},
    "boundary": {"generation_id", "mode"},
    "execution": {"qc_tool_version", "started_at", "finished_at", "status"},
}
_TOP = {"format", "schema_version", "producer_layout_version", "job_uuid",
        "created_at", "product_ident", "reference_period", "product_unit_code", *_SECTIONS}


def _text(value, *, maximum=500):
    if value is not None and (not isinstance(value, str) or not value
            or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise JobStorageError("Job provenance contains invalid text.")


def _timestamp(value, *, required=False):
    if value is None and not required:
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as error:
        raise JobStorageError("Job provenance timestamp is invalid.") from error


def validate_job_context(document, job_uuid):
    """Validate archived or on-disk producer evidence without choosing a location."""
    if (not isinstance(document, dict) or set(document) != _TOP
            or document.get("format") != CONTEXT_FORMAT
            or type(document.get("schema_version")) is not int
            or document["schema_version"] != CONTEXT_SCHEMA_VERSION
            or type(document.get("producer_layout_version")) is not int
            or document["producer_layout_version"] != CURRENT_LAYOUT_VERSION
            or document.get("job_uuid") != normalize_job_uuid(job_uuid)):
        raise JobStorageError("Job provenance format or identity is invalid.")
    for section, fields in _SECTIONS.items():
        if not isinstance(document[section], dict) or set(document[section]) != fields:
            raise JobStorageError("Job provenance fields are invalid.")
    for key in ("product_ident", "reference_period", "product_unit_code"):
        _text(document[key])
    _timestamp(document["created_at"], required=True)
    for key in ("started_at", "finished_at"):
        _timestamp(document["execution"][key])
    for section in ("input", "specification"):
        filename, checksum = document[section]["filename"], document[section]["sha256"]
        if filename is not None:
            safe_artifact_name(filename)
        if checksum is not None and (not isinstance(checksum, str) or not _SHA256.fullmatch(checksum)):
            raise JobStorageError("Job provenance checksum is invalid.")
    spec = document["specification"]
    if (spec["filename"] is None) != (spec["sha256"] is None):
        raise JobStorageError("Job specification provenance is incomplete.")
    source = document["input"]
    if source["source"] not in (None, "local", "s3"):
        raise JobStorageError("Job input provenance is invalid.")
    if not isinstance(source["hash_files"], list) or len(source["hash_files"]) > 25_000:
        raise JobStorageError("Job input hash scope is invalid.")
    for name in source["hash_files"]:
        safe_artifact_name(name)
    _text(source["reported_hash"], maximum=128)
    if document["boundary"]["mode"] not in (None, "managed", "legacy"):
        raise JobStorageError("Job boundary provenance is invalid.")
    _text(document["boundary"]["generation_id"], maximum=100)
    for key in ("qc_tool_version", "status"):
        _text(document["execution"][key], maximum=100)
    return document
