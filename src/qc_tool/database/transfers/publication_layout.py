"""Read publication role metadata from retained archive bytes without filesystem IO."""

import hashlib
import json

from qc_tool.jobs.context_schema import MAX_CONTEXT_BYTES
from qc_tool.frontend.dashboard.services.submissions.publication.job_layout import publication_output_directory

from .archive import TransferArchiveError


def publication_archive_output_directory(archive, prefix, manifest, files, directories):
    """Reuse the publication layout contract for a complete portable inventory."""

    if "output.d" in directories and "outputs" not in directories:
        return "output.d"  # Legacy job.json can be a much larger original recipe.
    document = None
    entry = files.get(("submissions", prefix + "job.json"))
    if entry is not None:
        if entry["size"] > MAX_CONTEXT_BYTES:
            raise TransferArchiveError("Retained publication provenance exceeds its size limit.")
        with archive.open_artifact(entry) as stream:
            payload = stream.read(MAX_CONTEXT_BYTES + 1)
        if len(payload) != entry["size"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise TransferArchiveError("Retained publication provenance differs from its archive inventory.")
        try:
            document = json.loads(payload)
        except (ValueError, UnicodeError):
            pass  # An old job.json may be an arbitrary original specification.
    try:
        return publication_output_directory(document, manifest, directories)
    except ValueError as error:
        raise TransferArchiveError("Retained publication provenance is invalid.") from error
