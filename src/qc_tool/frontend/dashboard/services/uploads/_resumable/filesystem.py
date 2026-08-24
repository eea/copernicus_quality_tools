"""Low-level, no-follow filesystem operations for resumable uploads."""

from __future__ import annotations

import errno
from hashlib import sha256
import os
from pathlib import Path
import stat
from typing import BinaryIO

from .errors import ResumableUploadError


COPY_CHUNK_SIZE = 1024 * 1024


def directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def open_directory(path: Path) -> int:
    try:
        descriptor = os.open(path, directory_flags())
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError(errno.ENOTDIR, "path is not a directory")
        return descriptor
    except OSError as exc:
        raise ResumableUploadError(
            "unsafe_upload_storage",
            "Upload storage is not safe.",
            500,
        ) from exc


def write_once_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def read_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def hash_regular_file_at(
    directory_descriptor: int,
    filename: str,
    *,
    max_bytes: int,
) -> tuple[int, bytes]:
    descriptor = None
    try:
        descriptor = os.open(
            filename,
            read_flags(),
            dir_fd=directory_descriptor,
        )
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode) or file_status.st_size > max_bytes:
            raise OSError("upload chunk is not a bounded regular file")
        digest = sha256()
        byte_count = 0
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            while True:
                block = source.read(COPY_CHUNK_SIZE)
                if not block:
                    break
                byte_count += len(block)
                if byte_count > max_bytes:
                    raise OSError("upload chunk grew beyond its bound")
                digest.update(block)
        return byte_count, digest.digest()
    except OSError as exc:
        raise ResumableUploadError(
            "unsafe_upload_staging",
            "Upload staging is not safe.",
            500,
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def copy_regular_file_at(
    directory_descriptor: int,
    filename: str,
    output: BinaryIO,
    *,
    max_bytes: int,
) -> int:
    descriptor = None
    try:
        descriptor = os.open(
            filename,
            read_flags(),
            dir_fd=directory_descriptor,
        )
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode) or file_status.st_size > max_bytes:
            raise OSError("upload chunk is not a bounded regular file")
        byte_count = 0
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            while True:
                block = source.read(COPY_CHUNK_SIZE)
                if not block:
                    break
                byte_count += len(block)
                if byte_count > max_bytes:
                    raise OSError("upload chunk grew beyond its bound")
                output.write(block)
        return byte_count
    except OSError as exc:
        raise ResumableUploadError(
            "unsafe_upload_staging",
            "Upload staging is not safe.",
            500,
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def regular_file_exists(path: Path) -> bool:
    """Check a staging entry without following its directory or file links."""

    try:
        parent_descriptor = os.open(path.parent, directory_flags())
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ResumableUploadError(
            "unsafe_upload_storage",
            "Upload storage is not safe.",
            500,
        ) from exc
    try:
        return regular_file_exists_at(parent_descriptor, path.name)
    finally:
        os.close(parent_descriptor)


def regular_file_exists_at(directory_descriptor: int, filename: str) -> bool:
    descriptor = None
    try:
        try:
            descriptor = os.open(
                filename,
                read_flags(),
                dir_fd=directory_descriptor,
            )
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ResumableUploadError(
                "unsafe_upload_staging",
                "Upload staging is not safe.",
                500,
            ) from exc
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ResumableUploadError(
                "unsafe_upload_staging",
                "Upload staging is not safe.",
                500,
            )
        return True
    finally:
        if descriptor is not None:
            os.close(descriptor)
