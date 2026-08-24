"""Deterministic content hashing for materialized S3 deliveries."""

from functools import partial
import hashlib

from qc_tool.common import HASH_ALGORITHM

from .transfer import COPY_CHUNK_BYTES


def hash_file(path):
    """Hash one file using the QC Tool's configured content algorithm."""

    digest = hashlib.new(HASH_ALGORITHM)
    with path.open("rb") as source:
        for chunk in iter(partial(source.read, COPY_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(paths):
    """Hash a stable filename/content sequence without path ambiguity."""

    digest = hashlib.new(HASH_ALGORITHM)
    for path in sorted(paths, key=lambda candidate: candidate.name.casefold()):
        name = path.name.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        with path.open("rb") as source:
            for chunk in iter(partial(source.read, COPY_CHUNK_BYTES), b""):
                digest.update(chunk)
    return digest.hexdigest()
