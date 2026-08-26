"""Low-level fsync operations required for durable activation."""

import errno
import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise
        logger.warning("Filesystem does not support directory fsync: %s", path.name)
    finally:
        os.close(descriptor)


def fsync_regular_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
