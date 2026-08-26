"""No-follow regular-file copying and checksum primitives."""

import hashlib
import os
import stat

from ..errors import PublicationError


COPY_BUFFER_BYTES = 1024 * 1024


def copy_regular_file(source, destination):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise PublicationError(
            "unsafe_job_artifact",
            "A publication source file could not be opened safely.",
            409,
        ) from exc
    digest = hashlib.sha256()
    size = 0
    try:
        source_status = os.fstat(descriptor)
        if not stat.S_ISREG(source_status.st_mode):
            raise PublicationError(
                "unsafe_job_artifact",
                "A publication source is not a regular file.",
                409,
            )
        with os.fdopen(descriptor, "rb", closefd=False) as source_stream:
            with destination.open("xb") as destination_stream:
                while True:
                    block = source_stream.read(COPY_BUFFER_BYTES)
                    if not block:
                        break
                    destination_stream.write(block)
                    digest.update(block)
                    size += len(block)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def write_owned_file(path, payload):
    with path.open("xb") as stream:
        stream.write(payload)


def inventory_entry(path, payload):
    return {
        "path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }
