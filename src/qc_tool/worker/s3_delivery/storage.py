"""No-follow local storage primitives for S3 downloads."""

import os
from pathlib import Path
import stat

from .errors import configuration_error


def prepare_destination(value):
    """Return a real private directory, creating only its final component."""

    destination = Path(value)
    try:
        destination_stat = destination.lstat()
    except FileNotFoundError:
        parent_stat = destination.parent.lstat()
        if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
            raise configuration_error("download parent is unsafe")
        destination.mkdir(mode=0o700)
        destination_stat = destination.lstat()
    if not stat.S_ISDIR(destination_stat.st_mode) or stat.S_ISLNK(destination_stat.st_mode):
        raise configuration_error("download directory is unsafe")
    return destination


def open_directory(path):
    """Open a directory descriptor without following its final symlink."""

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(str(path), flags)
    except OSError as exc:
        raise configuration_error("download directory cannot be opened") from exc


def remove_created_files(paths, logger):
    """Best-effort removal restricted to regular, non-symlink files."""

    for path in reversed(paths):
        try:
            if path.is_file() and not path.is_symlink():
                path.unlink()
        except OSError:
            logger.warning("Could not remove a partial S3 delivery file.")
