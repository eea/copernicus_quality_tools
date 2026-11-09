"""Versioned job subnamespaces admitted by retained-file archive readers."""

from pathlib import Path

from .archive import TransferArchiveError
from .job_locations import archive_job_contexts


CANONICAL_FOLDERS = frozenset({"specification", "reports", "outputs"})


def job_artifact_allowed(key, *, directory=False, context=None, reference_only=False):
    parts = Path(key).parts
    if len(parts) == 1:
        return directory
    if parts[1] in CANONICAL_FOLDERS:
        if context is None and not reference_only:
            return False
        if directory:
            return len(parts) == 2 or parts[1] == "outputs"
        if parts[1] == "specification":
            return len(parts) == 3 and (reference_only or parts[2] == context["specification"]["filename"])
        return len(parts) >= 3 if parts[1] == "outputs" else len(parts) == 3
    if parts[1] == "logs":
        return False
    if directory:
        return parts[1] == "output.d"
    return (len(parts) == 2 and not parts[1].lower().endswith((".log", ".stdout", ".pre"))) or (
        len(parts) > 2 and parts[1] == "output.d")


def validate_canonical_job_folders(archive):
    """A nested canonical payload requires its exact validated producer context."""
    contexts = archive_job_contexts(archive)
    from qc_tool.jobs import recognize_job_directory
    for directory, entries in ((False, archive.entries), (True, archive.directories)):
        for entry in entries:
            parts = Path(entry["key"]).parts
            if entry["root"] != "work" or len(parts) < 2 or parts[1] not in CANONICAL_FOLDERS:
                continue
            identity = recognize_job_directory(parts[0])
            context = contexts.get(identity)
            if not job_artifact_allowed(entry["key"], directory=directory, context=context):
                raise TransferArchiveError("Canonical job artifacts lack their exact validated context.")
    return contexts
