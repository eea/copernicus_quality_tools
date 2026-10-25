"""Private descriptor-based journals for reversible file and folder moves."""

import ctypes
from datetime import datetime, timezone
import errno
import json
import os
import stat
import sys
from uuid import uuid4

from . import files
from .files import StorageError


JOURNAL_LIMIT = 32 * 1024


def private_directory(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    descriptor = os.open(name, files._DIRECTORY_FLAGS, dir_fd=parent)
    status = os.fstat(descriptor)
    if status.st_mode & 0o077 or status.st_uid != os.geteuid():
        os.close(descriptor)
        raise StorageError("Trash storage must be a private, application-owned real directory.")
    return descriptor


def write_journal(directory, journal):
    journal["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(journal, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    if len(payload) > JOURNAL_LIMIT:
        raise StorageError("The trash journal exceeds its supported size.")
    name = ".journal-" + uuid4().hex
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(name, "journal.json", src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def read_journal(directory):
    descriptor = os.open("journal.json", files._FILE_FLAGS, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
            raise StorageError("The trash journal is unsafe. Keep its files for recovery.")
        payload = handle.read(JOURNAL_LIMIT + 1)
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    def invalid_constant(_value):
        raise ValueError
    try:
        if len(payload) > JOURNAL_LIMIT:
            raise ValueError
        document = json.loads(payload, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
        if not isinstance(document, dict):
            raise ValueError
        return document
    except (ValueError, UnicodeError, RecursionError) as error:
        raise StorageError("The trash journal cannot be read safely. Keep its files for recovery.") from error


def rename_exclusive(source_parent, source, destination_parent, destination):
    """Atomically rename without replacing any existing file or directory."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename, flag = libc.renameat2, 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        rename, flag = libc.renameatx_np, 4  # RENAME_EXCL
    else:
        raise OSError(errno.ENOTSUP, "exclusive directory rename is unavailable")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(source_parent, os.fsencode(source), destination_parent, os.fsencode(destination), flag) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
