"""In-order incremental assembly that keeps finishing a large upload cheap.

Each chunk request appends every stored chunk that continues the assembled
prefix to the private ``.assembling`` file while it holds the upload lock. The
file is synchronized before ``.assembling.progress`` records the appended chunk
count, so the marker never claims bytes that a host crash could lose. Bytes
beyond the marker are discarded and appended again from the retained chunks.
"""

from __future__ import annotations

import errno
import os
import re
import stat

from .descriptor import ResumableUploadDescriptor
from .errors import ResumableUploadError, storage_failure
from .filesystem import copy_regular_file_at
from .filesystem import read_flags
from .filesystem import regular_file_exists_at
from .filesystem import write_once_flags


ASSEMBLING = ".assembling"
PROGRESS = ".assembling.progress"
_PROGRESS_TEMPORARY = PROGRESS + ".tmp"
_PROGRESS_PATTERN = re.compile(rb"(0|[1-9][0-9]{0,5})\Z")


def extend_assembly(descriptor: ResumableUploadDescriptor, chunk_paths, chunks_descriptor: int) -> bool:
    """Append stored chunks continuing the durable prefix; return completeness.

    The caller holds the upload lock for ``chunks_descriptor``.
    """

    appended = _read_progress(descriptor, chunks_descriptor)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        output_descriptor = os.open(ASSEMBLING, flags, 0o640, dir_fd=chunks_descriptor)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _unsafe_staging() from exc
        raise storage_failure(exc, operation="opening the upload assembly") from exc
    with os.fdopen(output_descriptor, "r+b") as output:
        try:
            if not stat.S_ISREG(os.fstat(output.fileno()).st_mode):
                raise _unsafe_staging()
            offset = _prefix_size(descriptor, appended)
            if os.fstat(output.fileno()).st_size < offset:
                # The marker outlived its file, for example after an
                # interrupted publication. Rebuild from the retained chunks.
                appended, offset = 0, 0
            output.truncate(offset)
            output.seek(offset)
            previous = appended
            while appended < descriptor.total_chunks:
                name = chunk_paths[appended].name
                if not regular_file_exists_at(chunks_descriptor, name):
                    break
                expected = descriptor.expected_size_for_chunk(appended + 1)
                written = copy_regular_file_at(chunks_descriptor, name, output, max_bytes=expected)
                if written != expected:
                    raise ResumableUploadError(
                        "invalid_upload_chunk_size",
                        "An upload chunk size differs from its declaration.",
                    )
                appended += 1
            if appended != previous:
                output.flush()
                os.fsync(output.fileno())
                _write_progress(chunks_descriptor, appended)
        except ResumableUploadError:
            raise
        except OSError as exc:
            raise storage_failure(exc, operation="appending to the upload assembly") from exc
    return appended == descriptor.total_chunks


def complete_assembly(descriptor: ResumableUploadDescriptor, chunk_paths, chunks_descriptor: int, name: str) -> None:
    """Rename the durable, exact-size assembly to ``name`` for publication."""

    if not extend_assembly(descriptor, chunk_paths, chunks_descriptor):
        raise ResumableUploadError("upload_incomplete", "The upload is not complete.", 409)
    try:
        if os.stat(ASSEMBLING, dir_fd=chunks_descriptor, follow_symlinks=False).st_size != descriptor.total_size:
            raise ResumableUploadError(
                "invalid_upload_size",
                "The uploaded data size differs from its declaration.",
            )
        os.replace(ASSEMBLING, name, src_dir_fd=chunks_descriptor, dst_dir_fd=chunks_descriptor)
    except ResumableUploadError:
        raise
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "The uploaded delivery could not be assembled.",
            500,
        ) from exc
    _best_effort_unlink(chunks_descriptor, PROGRESS)


def discard_assembly_progress(chunks_descriptor: int) -> None:
    for name in (ASSEMBLING, PROGRESS, _PROGRESS_TEMPORARY):
        _best_effort_unlink(chunks_descriptor, name)


def _prefix_size(descriptor, appended):
    if appended == descriptor.total_chunks:
        return descriptor.total_size
    return appended * descriptor.chunk_size


def _read_progress(descriptor, chunks_descriptor):
    try:
        progress_descriptor = os.open(PROGRESS, read_flags() | os.O_NONBLOCK, dir_fd=chunks_descriptor)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise _unsafe_staging() from exc
    with os.fdopen(progress_descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise _unsafe_staging()
        content = source.read(8)
    if not _PROGRESS_PATTERN.fullmatch(content):
        # An unsynchronized marker may be empty after a host crash. It never
        # holds a larger count, so restarting from zero is always safe.
        return 0
    return min(int(content), descriptor.total_chunks)


def _write_progress(chunks_descriptor, appended):
    # The marker itself is not synchronized: losing it only causes a rebuild.
    _best_effort_unlink(chunks_descriptor, _PROGRESS_TEMPORARY)
    descriptor = os.open(_PROGRESS_TEMPORARY, write_once_flags(), 0o600, dir_fd=chunks_descriptor)
    with os.fdopen(descriptor, "wb") as target:
        target.write(str(appended).encode("ascii"))
    os.replace(_PROGRESS_TEMPORARY, PROGRESS, src_dir_fd=chunks_descriptor, dst_dir_fd=chunks_descriptor)


def _best_effort_unlink(chunks_descriptor, name):
    try:
        os.unlink(name, dir_fd=chunks_descriptor)
    except OSError:
        pass


def _unsafe_staging():
    return ResumableUploadError("unsafe_upload_staging", "Upload staging is not safe.", 500)
