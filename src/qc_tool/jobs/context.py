"""Bounded, atomic storage of measured QC run provenance."""

from datetime import datetime, timezone
import json
import os
import stat
from uuid import uuid4

from .context_schema import (
    CONTEXT_FORMAT, CONTEXT_SCHEMA_VERSION, MAX_CONTEXT_BYTES, validate_job_context,
)
from .errors import JobStorageError
from .paths import CURRENT_LAYOUT_VERSION


_FACTS = {
    "product_ident": ("product_ident",), "reference_period": ("reference_period",),
    "product_unit_code": ("product_unit_code",),
    "input_filename": ("input", "filename"), "input_source": ("input", "source"),
    "input_sha256": ("input", "sha256"), "input_hash_files": ("input", "hash_files"),
    "reported_input_hash": ("input", "reported_hash"),
    "specification_filename": ("specification", "filename"),
    "specification_sha256": ("specification", "sha256"),
    "boundary_generation_id": ("boundary", "generation_id"),
    "boundary_mode": ("boundary", "mode"),
    "qc_tool_version": ("execution", "qc_tool_version"),
    "started_at": ("execution", "started_at"), "finished_at": ("execution", "finished_at"),
    "status": ("execution", "status"),
}


def initial_job_context(paths):
    return {
        "format": CONTEXT_FORMAT, "schema_version": CONTEXT_SCHEMA_VERSION,
        "producer_layout_version": CURRENT_LAYOUT_VERSION, "job_uuid": paths.job_uuid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "product_ident": None, "reference_period": None, "product_unit_code": None,
        "input": {"filename": None, "source": None, "sha256": None,
                  "hash_files": [], "reported_hash": None},
        "specification": {"filename": None, "sha256": None},
        "boundary": {"generation_id": None, "mode": None},
        "execution": {"qc_tool_version": None, "started_at": None,
                      "finished_at": None, "status": None},
    }


def read_job_context(paths):
    """Read recognized producer metadata; absence on legacy jobs stays unknown."""
    try:
        fd = os.open(paths.metadata_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise JobStorageError("Job provenance is not a regular file.")
            raw = stream.read(MAX_CONTEXT_BYTES + 1)
    except FileNotFoundError:
        if paths.legacy:
            return None
        raise JobStorageError("The canonical job provenance is missing.") from None
    except OSError as error:
        raise JobStorageError("Job provenance cannot be read safely.") from error
    try:
        if len(raw) > MAX_CONTEXT_BYTES:
            raise ValueError
        document = json.loads(raw, object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise JobStorageError("Job provenance JSON is invalid.") from error
    if paths.legacy and isinstance(document, dict) and document.get("format") != CONTEXT_FORMAT:
        return None  # A historical product may itself have been named job.json.
    return validate_job_context(document, paths.job_uuid)


def write_job_context(paths, document):
    """Write only new-layout producer records; never rewrite historical evidence."""
    if paths.legacy:
        raise JobStorageError("Legacy job provenance must not be synthesized or rewritten.")
    validate_job_context(document, paths.job_uuid)
    raw = json.dumps(document, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_CONTEXT_BYTES or paths.metadata_path.is_symlink():
        raise JobStorageError("Job provenance cannot be published safely.")
    temporary = paths.directory / (".job-" + uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, paths.metadata_path)
        fd = os.open(paths.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def record_job_context(paths, **facts):
    """Record explicit observations only; unknown fields are rejected."""
    if paths.legacy:
        return None
    document = read_job_context(paths)
    for name, value in facts.items():
        if name not in _FACTS:
            raise JobStorageError("Unsupported job provenance observation.")
        keys = _FACTS[name]
        target = document if len(keys) == 1 else document[keys[0]]
        if name not in {"status", "finished_at"} and target[keys[-1]] not in (None, []):
            if target[keys[-1]] != value:
                raise JobStorageError("Measured job provenance cannot be replaced.")
        target[keys[-1]] = value
    write_job_context(paths, document)
    return document


def _unique_pairs(items):
    document = {}
    for key, value in items:
        if key in document:
            raise ValueError("Repeated provenance key.")
        document[key] = value
    return document
