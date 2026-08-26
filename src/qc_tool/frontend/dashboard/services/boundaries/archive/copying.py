"""Bounded, hashed copying of an uploaded boundary archive."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import BinaryIO, Optional, Union

from ..errors import BoundaryPackageInvalid, BoundaryPackageLimitExceeded
from .constants import COPY_CHUNK_SIZE


def copy_archive_bounded(
    source: Union[BinaryIO, str, os.PathLike], destination: Path, max_bytes: int
) -> tuple[int, str]:
    """Copy an upload into private staging while hashing and bounding it."""

    digest = hashlib.sha256()
    byte_count = 0
    source_stream: BinaryIO
    close_source = False
    original_position: Optional[int] = None

    if isinstance(source, (str, os.PathLike)):
        try:
            source_stream = open(source, "rb")
        except OSError as exc:
            raise BoundaryPackageInvalid("uploaded archive cannot be read") from exc
        close_source = True
    elif hasattr(source, "read"):
        source_stream = source
        try:
            original_position = source_stream.tell()
            source_stream.seek(0)
        except (AttributeError, OSError, io.UnsupportedOperation):
            original_position = None
    else:
        raise TypeError("archive must be a binary file object or filesystem path")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        file_descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(file_descriptor, "wb") as output:
            while True:
                chunk = source_stream.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise BoundaryPackageInvalid("uploaded archive is not a binary stream")
                byte_count += len(chunk)
                if byte_count > max_bytes:
                    raise BoundaryPackageLimitExceeded("compressed archive is too large")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    finally:
        if close_source:
            source_stream.close()
        elif original_position is not None:
            try:
                source_stream.seek(original_position)
            except (OSError, io.UnsupportedOperation):
                pass

    if byte_count == 0:
        raise BoundaryPackageInvalid("uploaded archive is empty")
    return byte_count, digest.hexdigest()
