"""Preserve exact specification snapshot bytes and resolve their original names."""

import hashlib
import re

from .context import read_job_context, record_job_context
from .errors import JobStorageError
from .files import publish_job_bytes, read_regular_bytes


MAX_SPECIFICATION_BYTES = 1024 * 1024


def snapshot_specification(paths, source_name, payload, product_ident):
    name = product_ident + ".json" if paths.legacy else source_name
    destination = paths.specification_path(name)
    publish_job_bytes(destination, payload)
    record_job_context(
        paths, product_ident=product_ident, specification_filename=name,
        specification_sha256=hashlib.sha256(payload).hexdigest(),
    )
    return destination


def read_specification_snapshot(paths, product_ident):
    context = read_job_context(paths)
    if context is not None:
        spec = context["specification"]
        if spec["filename"] is None:
            raise JobStorageError("The job specification snapshot is unavailable.")
        path = paths.specification_path(spec["filename"])
        payload = read_regular_bytes(path, limit=MAX_SPECIFICATION_BYTES)
        if hashlib.sha256(payload).hexdigest() != spec["sha256"]:
            raise JobStorageError("The job specification snapshot checksum changed.")
        if context["product_ident"] != product_ident:
            raise JobStorageError("The job specification identity does not match.")
        return payload
    candidates = [p for p in paths.specification_dir.glob("*.json")
                  if p.stem.lower() == product_ident]
    digest_named = not candidates
    if digest_named:
        candidates = [p for p in paths.specification_dir.glob("*.json")
                      if re.fullmatch(r"[a-f0-9]{64}", p.stem)]
    if len(candidates) != 1:
        raise JobStorageError("The historical job specification is missing or ambiguous.")
    path = candidates[0]
    payload = read_regular_bytes(path, limit=MAX_SPECIFICATION_BYTES)
    if digest_named and hashlib.sha256(payload).hexdigest() != path.stem:
        raise JobStorageError("The historical specification checksum changed.")
    return payload
