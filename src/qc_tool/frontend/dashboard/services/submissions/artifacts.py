"""Read the retained submission files named by its immutable receipt."""

import hashlib
import json
from pathlib import Path, PurePosixPath

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable, open_regular_artifact
from .publication.integrity import _expected_inventory, PublicationIntegrityError
from .publication.manifest import MANIFEST_FILENAME, MAX_MANIFEST_BYTES
from .storage import artifact_directory


def submission_inventory(submission):
    if submission.publication_state != "published" or not CONFIG.get("submission_dir"):
        raise ArtifactUnavailable
    try:
        path = artifact_directory(CONFIG["submission_dir"], submission.artifact_key)
        with open_regular_artifact(path, MANIFEST_FILENAME) as stream:
            payload = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError
        document = json.loads(payload)
        if not isinstance(document, dict):
            raise ValueError
        stated_digest = document.pop("artifact_sha256")
        digest = hashlib.sha256(json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if digest != stated_digest or digest != submission.artifact_digest:
            raise ValueError
        if str(document.get("submission_id")) != str(submission.pk):
            raise ValueError
        inventory = _expected_inventory(document, MANIFEST_FILENAME)
        return path, inventory
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, PublicationIntegrityError) as exc:
        raise ArtifactUnavailable from exc


def open_submission_file(submission, filename):
    root, inventory = submission_inventory(submission)
    if filename not in inventory:
        raise ArtifactUnavailable
    parts = PurePosixPath(filename).parts
    directory = _real_directory(root, parts[:-1])
    stream = open_regular_artifact(directory, parts[-1])
    expected_digest, expected_size = inventory[filename]
    try:
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        if size != expected_size or digest.hexdigest() != expected_digest:
            raise ArtifactUnavailable
        stream.seek(0)
        return stream
    except Exception:
        stream.close()
        raise


def _real_directory(root, parts):
    directory = Path(root)
    if directory.is_symlink() or not directory.is_dir():
        raise ArtifactUnavailable
    for part in parts:
        if part in {".", ".."}:
            raise ArtifactUnavailable
        directory /= part
        if directory.is_symlink() or not directory.is_dir():
            raise ArtifactUnavailable
    return directory
