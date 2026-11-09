"""Recognize retained producer provenance without guessing a job layout."""

import json

from qc_tool.jobs import JobStorageError, validate_job_context
from qc_tool.jobs.context_schema import CONTEXT_FORMAT, MAX_CONTEXT_BYTES
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable, open_regular_artifact


def retained_output_directory(root, manifest, directories):
    """Old flat artifacts need output.d; recognized canonical runs need outputs."""

    if "output.d" in directories and "outputs" not in directories:
        return "output.d"
    files = manifest.get("files", [])
    if not any(item.get("path") == "job.json" for item in files):
        return "output.d"
    try:
        with open_regular_artifact(root, "job.json") as stream:
            payload = stream.read(MAX_CONTEXT_BYTES + 1)
        if len(payload) > MAX_CONTEXT_BYTES:
            raise ValueError("Retained job provenance is too large.")
        document = json.loads(payload)
    except (ArtifactUnavailable, OSError) as exc:
        raise ValueError("Retained job provenance cannot be read safely.") from exc
    except (UnicodeError, json.JSONDecodeError):
        return "output.d"  # A historical specification may itself be job.json.
    return publication_output_directory(document, manifest, directories)


def publication_output_directory(document, manifest, directories):
    """Choose retained roles from loaded provenance, usable by files and archives."""

    if "output.d" in directories and "outputs" not in directories:
        return "output.d"
    if not isinstance(document, dict) or document.get("format") != CONTEXT_FORMAT:
        return "output.d"
    try:
        validate_job_context(document, manifest["job_id"])
    except (JobStorageError, KeyError) as exc:
        raise ValueError("Retained job provenance is invalid.") from exc
    specification = document["specification"]
    expected_name = "specification/" + (specification["filename"] or "")
    retained = next((item for item in manifest.get("files", []) if item.get("path") == expected_name), None)
    if retained is None or retained.get("sha256") != specification["sha256"]:
        raise ValueError("The retained specification differs from its execution provenance.")
    if "output.d" in directories:
        raise ValueError("The retained job output layout is ambiguous.")
    return "outputs"
