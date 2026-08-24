"""Confinement and no-follow opening for downloadable QC artifacts."""

import os
from pathlib import Path
import stat
import unicodedata

from qc_tool.common import compose_job_dir
from qc_tool.common import JOB_OUTPUT_DIRNAME
from qc_tool.common import load_job_result

from .errors import ArtifactUnavailable


DEFAULT_TEXT_ARTIFACT_BYTES = 10 * 1024 * 1024


def open_job_attachment(job_uuid, filename):
    """Open one regular file directly below a job's output directory."""

    output_root = compose_job_dir(str(job_uuid)) / JOB_OUTPUT_DIRNAME
    return open_regular_artifact(output_root, filename)


def open_job_report(job_uuid):
    """Open the report named by trusted job state, confined to the job root."""

    try:
        job_result = load_job_result(str(job_uuid))
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactUnavailable from exc
    if not isinstance(job_result, dict):
        raise ArtifactUnavailable
    report_filename = job_result.get("report_filename", "report.pdf")
    return (
        open_regular_artifact(compose_job_dir(str(job_uuid)), report_filename),
        report_filename,
    )


def open_regular_artifact(root, filename):
    """Open a new regular file confined directly below ``root``.

    Returning an already-open descriptor prevents the view from validating one
    path and subsequently opening a replacement symbolic link.
    """

    filename = _validated_filename(filename)
    unresolved_root = Path(root)
    if unresolved_root.is_symlink():
        raise ArtifactUnavailable
    try:
        resolved_root = unresolved_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArtifactUnavailable from exc
    if not resolved_root.is_dir():
        raise ArtifactUnavailable

    candidate = resolved_root / filename
    if candidate.is_symlink():
        raise ArtifactUnavailable
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArtifactUnavailable from exc
    if resolved_candidate.parent != resolved_root:
        raise ArtifactUnavailable

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(resolved_candidate, flags)
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            raise ArtifactUnavailable
        return os.fdopen(descriptor, "rb")
    except (OSError, ArtifactUnavailable) as exc:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(exc, ArtifactUnavailable):
            raise
        raise ArtifactUnavailable from exc


def read_text_artifact(
    root,
    filename,
    *,
    maximum_bytes=DEFAULT_TEXT_ARTIFACT_BYTES,
):
    """Read a bounded UTF-8 text artifact without following links."""

    if (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes <= 0
    ):
        raise ValueError("maximum_bytes must be a positive integer")
    with open_regular_artifact(root, filename) as artifact:
        payload = artifact.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        payload = payload[:maximum_bytes] + b"\n[log truncated]\n"
    return payload.decode("utf-8", errors="replace")


def _validated_filename(value):
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ArtifactUnavailable
    if value != unicodedata.normalize("NFC", value):
        raise ArtifactUnavailable
    if Path(value).name != value or "\\" in value or "\x00" in value:
        raise ArtifactUnavailable
    if len(value.encode("utf-8")) > 255:
        raise ArtifactUnavailable
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise ArtifactUnavailable
    return value
