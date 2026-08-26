"""Cross-process serialization for boundary package publication."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import time
from typing import Iterator, Optional

from ..errors import (
    BoundaryPackageBusy,
    BoundaryPackageConfigurationError,
    BoundaryPackageError,
)
from .constants import LOCK_FILENAME


@contextmanager
def boundary_package_lock(root: Path, *, timeout: float) -> Iterator[None]:
    """Serialize all staging and activation work across cooperating processes."""

    descriptor = _open_lock(root / LOCK_FILENAME)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BoundaryPackageBusy("promotion lock timed out")
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _open_lock(lock_path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise BoundaryPackageConfigurationError("promotion lock is not a regular file")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BoundaryPackageError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BoundaryPackageConfigurationError("promotion lock cannot be opened") from exc
