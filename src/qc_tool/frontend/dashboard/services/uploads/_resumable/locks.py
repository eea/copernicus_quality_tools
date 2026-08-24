"""Bounded process locks for finalizing an upload."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
from math import isfinite
import os
from pathlib import Path
import stat
from time import monotonic, sleep
from typing import Iterator

from .errors import ResumableUploadError
from .filesystem import open_directory


DEFAULT_LOCK_TIMEOUT = 30.0


@contextmanager
def upload_lock(
    chunks_dir: Path,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> Iterator[int]:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not isfinite(timeout)
        or timeout < 0
    ):
        raise ValueError("timeout must be a non-negative number")

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    descriptor = None
    directory_descriptor = open_directory(chunks_dir)
    try:
        descriptor = os.open(
            ".upload.lock",
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("upload lock is not a regular file")
        _acquire_with_timeout(descriptor, timeout)
        yield directory_descriptor
    except ResumableUploadError:
        raise
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "The upload cannot be finalized safely.",
            500,
        ) from exc
    finally:
        try:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        finally:
            os.close(directory_descriptor)


def _acquire_with_timeout(descriptor: int, timeout: float) -> None:
    deadline = monotonic() + timeout
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if monotonic() >= deadline:
                raise ResumableUploadError(
                    "upload_busy",
                    "The upload is currently being finalized. Please retry.",
                    409,
                )
            sleep(min(0.05, max(0, deadline - monotonic())))
