"""Physical job destinations behind stable logical transfer identities."""

import hashlib
import os
from pathlib import Path

from qc_tool.jobs import (
    job_paths_for_layout, recognize_job_directory, read_job_context,
    resolve_job_paths, validate_job_context,
)

from .archive import TransferArchiveError, _json


class JobStorageRoots(dict):
    """Operation-local destination choices; never serialized into a package."""

    def __init__(self, roots):
        super().__init__((key, Path(value)) for key, value in roots.items())
        self.job_targets = {}


def archive_job_contexts(archive):
    """Validate recognized context bytes without consulting target storage."""
    contexts = {}
    for entry in archive.entries:
        parts = Path(entry["key"]).parts
        if entry["root"] != "work" or len(parts) != 2 or parts[1] != "job.json":
            continue
        identity = recognize_job_directory(parts[0])
        if identity is None:
            continue
        if entry["size"] > 256 * 1024:
            raise TransferArchiveError("Retained job context exceeds its size limit.")
        with archive.open_artifact(entry) as stream:
            payload = stream.read(256 * 1024 + 1)
        if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise TransferArchiveError("Retained job context differs from the verified archive.")
        document = _json(payload)
        if not isinstance(document, dict) or document.get("format") != "qc-tool-job":
            continue  # Historical arbitrary JSON is not a layout declaration.
        try:
            context = validate_job_context(document, identity)
            contexts[str(identity)] = context
        except (OSError, ValueError, TypeError) as error:
            raise TransferArchiveError("Retained job layout context is invalid or ambiguous.") from error
    return contexts


def prepare_job_roots(roots, archive):
    """Bind each archived context to a stable, create-only physical destination."""
    result = JobStorageRoots(roots)
    if "work" not in result:
        return result
    canonical_payloads = {recognize_job_directory(parts[0])
        for item in (*archive.entries, *archive.directories)
        if item["root"] == "work" and len(parts := Path(item["key"]).parts) > 1
        and parts[1] in {"specification", "reports", "outputs"}}
    contexts = archive_job_contexts(archive)
    identities = {recognize_job_directory(Path(item["key"]).parts[0])
        for item in (*archive.entries, *archive.directories) if item["root"] == "work"}
    for identity in identities - contexts.keys() - {None}:
        canonical = job_paths_for_layout(result["work"], identity, 2)
        if os.path.lexists(canonical.directory):
            raise TransferArchiveError("Legacy job artifacts conflict with an existing canonical job location.")
    for identity, context in contexts.items():
        canonical = job_paths_for_layout(result["work"], identity, 2)
        legacy = job_paths_for_layout(result["work"], identity, 1)
        if os.path.lexists(canonical.directory) and os.path.lexists(legacy.directory):
            raise TransferArchiveError("Both job storage layouts exist for this identity.")
        selected = legacy if os.path.lexists(legacy.directory) else canonical
        if selected.legacy and identity in canonical_payloads:
            raise TransferArchiveError("Canonical job artifacts conflict with an existing legacy job location.")
        result.job_targets[identity] = (selected, context)
    return result


def job_target(roots, identity):
    return getattr(roots, "job_targets", {}).get(str(identity))


def job_storage_key(roots, key):
    """Translate one established job archive key to its selected physical path."""
    parts = Path(key).parts
    identity = recognize_job_directory(parts[0]) if parts else None
    if identity is None:
        return key
    selected = job_target(roots, identity)
    try:
        if selected is None:
            paths = resolve_job_paths(roots["work"], identity)
            if not paths.directory.exists():
                return key  # Existing no-context archives restore at old names.
            context = read_job_context(paths)
        else:
            paths, context = selected
    except (OSError, ValueError) as error:
        raise TransferArchiveError("Retained job storage has an unsafe or ambiguous layout.") from error
    relative = list(parts[1:])
    if not paths.legacy and relative:
        if relative[0] == "output.d":
            relative[0] = paths.output_dir.name
        elif len(relative) == 1 and relative[0] not in {"job.json", "result.json", "specification", "reports", "outputs", "logs"}:
            filename = (context.get("specification") or {}).get("filename")
            relative.insert(0, paths.specification_dir.name if relative[0] == filename else paths.reports_dir.name)
    return Path(paths.directory.name, *relative).as_posix()


def initialize_job_directories(plan):
    """Create empty canonical role folders through the existing durable journal."""
    for paths, _context in getattr(plan.roots, "job_targets", {}).values():
        if not paths.legacy:
            for directory in (paths.specification_dir, paths.reports_dir, paths.output_dir, paths.logs_dir):
                plan._directory(directory)
