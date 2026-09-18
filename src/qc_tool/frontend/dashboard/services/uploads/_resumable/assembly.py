"""Exact-size assembly and no-overwrite publication of completed uploads."""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import stat

from .descriptor import ResumableUploadDescriptor
from .errors import ResumableUploadError
from .filesystem import COPY_CHUNK_SIZE
from .filesystem import copy_regular_file_at
from .filesystem import open_directory
from .filesystem import read_flags
from .filesystem import regular_file_exists_at
from .filesystem import write_once_flags
from .locks import DEFAULT_LOCK_TIMEOUT, upload_lock
from .paths import ResumableUploadPaths, expected_chunk_paths


def assemble_chunks(
    descriptor: ResumableUploadDescriptor,
    paths: ResumableUploadPaths,
    *,
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> Path:
    """Assemble and atomically publish a delivery without overwriting a file."""

    chunk_paths = expected_chunk_paths(descriptor, paths)
    with upload_lock(paths.chunks_dir, timeout=lock_timeout) as chunks_descriptor:
        target_directory = open_directory(paths.user_root)
        try:
            _reject_existing_target(paths, target_directory)
            if not all(
                regular_file_exists_at(chunks_descriptor, path.name)
                for path in chunk_paths
            ):
                raise ResumableUploadError(
                    "upload_incomplete",
                    "The upload is not complete.",
                    409,
                )

            _discard_stale_assembly(chunks_descriptor)
            try:
                _write_assembly(descriptor, chunk_paths, chunks_descriptor)
                _publish_assembly(
                    paths,
                    chunks_descriptor,
                    target_directory,
                )
            finally:
                _best_effort_unlink(chunks_descriptor, ".assembled")

            _discard_published_chunks(chunks_descriptor, chunk_paths)
            return paths.target_path
        finally:
            os.close(target_directory)


def publish_for_registration(descriptor, paths, chunks_descriptor):
    """Publish or recover this upload's inode while retaining its ownership link.

    The caller holds both filename and upload locks through database registration
    and rejects any unrelated active delivery record before calling this helper.
    Keeping ``.assembled`` until registration succeeds makes a process interruption
    recoverable. A fresh upload identifier can also recover an unregistered file,
    but only after all incoming bytes have been assembled and verified identical.
    """

    target_directory = open_directory(paths.user_root)
    try:
        if owned_publication(paths, chunks_descriptor, target_directory):
            return paths.target_path
        chunk_paths = expected_chunk_paths(descriptor, paths)
        if not all(regular_file_exists_at(chunks_descriptor, path.name) for path in chunk_paths):
            raise ResumableUploadError("upload_incomplete", "The upload is not complete.", 409)
        _discard_stale_assembly(chunks_descriptor)
        _write_assembly(descriptor, chunk_paths, chunks_descriptor)
        os.fsync(chunks_descriptor)
        try:
            _publish_assembly(paths, chunks_descriptor, target_directory)
        except ResumableUploadError as exc:
            if exc.code != "delivery_file_exists":
                raise
            _recover_identical_publication(paths, chunks_descriptor, target_directory)
        return paths.target_path
    finally:
        os.close(target_directory)


def _recover_identical_publication(paths, chunks_descriptor, target_directory):
    """Keep the existing file and adopt its inode only after a full comparison.

    Pin the destination before inspecting it, then atomically replace only the
    private ownership link. An interruption leaves either complete incoming
    chunks to compare again or a verified ownership link to resume registration.
    """

    recovery_name = ".recovered"
    try:
        _best_effort_unlink(chunks_descriptor, recovery_name)
        os.link(
            paths.target_path.name, recovery_name,
            src_dir_fd=target_directory, dst_dir_fd=chunks_descriptor,
            follow_symlinks=False,
        )
        with ExitStack() as stack:
            sources = []
            snapshots = []
            for name in (recovery_name, ".assembled"):
                # Nonblocking opens also reject FIFOs without waiting for a writer.
                descriptor = os.open(name, read_flags() | os.O_NONBLOCK, dir_fd=chunks_descriptor)
                source = stack.enter_context(os.fdopen(descriptor, "rb"))
                status = os.fstat(source.fileno())
                if not stat.S_ISREG(status.st_mode):
                    raise _unregistered_file_exists()
                sources.append(source)
                snapshots.append(_file_snapshot(status))
            if snapshots[0][2] != snapshots[1][2]:
                raise _unregistered_file_exists()
            remaining = snapshots[0][2]
            while remaining:
                size = min(remaining, COPY_CHUNK_SIZE)
                existing, incoming = (source.read(size) for source in sources)
                if len(existing) != size or existing != incoming:
                    raise _unregistered_file_exists()
                remaining -= size
            current = [_file_snapshot(os.fstat(source.fileno())) for source in sources]
            target = os.stat(paths.target_path.name, dir_fd=target_directory, follow_symlinks=False)
            if current != snapshots or _file_snapshot(target) != snapshots[0]:
                raise _unregistered_file_exists()
            os.replace(
                recovery_name, ".assembled",
                src_dir_fd=chunks_descriptor, dst_dir_fd=chunks_descriptor,
            )
            os.fsync(chunks_descriptor)
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "The existing upload could not be recovered safely. Retry the upload.", 500,
        ) from exc
    finally:
        _best_effort_unlink(chunks_descriptor, recovery_name)


def _file_snapshot(status):
    return (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns)


def _unregistered_file_exists():
    return ResumableUploadError(
        "delivery_file_exists",
        "A different file with this name remains in upload storage but is not registered "
        "as a delivery. Rename this ZIP or ask an administrator to resolve the stored file.",
        409,
    )


def owned_publication(paths, chunks_descriptor, target_directory):
    try:
        staged = os.stat(".assembled", dir_fd=chunks_descriptor, follow_symlinks=False)
        target = os.stat(paths.target_path.name, dir_fd=target_directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(staged.st_mode) or not stat.S_ISREG(target.st_mode):
        raise ResumableUploadError("unsafe_upload_staging", "Upload staging is not safe.", 500)
    return (staged.st_dev, staged.st_ino) == (target.st_dev, target.st_ino)


def _reject_existing_target(
    paths: ResumableUploadPaths,
    target_directory: int,
) -> None:
    try:
        os.stat(
            paths.target_path.name,
            dir_fd=target_directory,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "The delivery destination could not be inspected.",
            500,
        ) from exc
    raise _file_exists()


def _file_exists() -> ResumableUploadError:
    return ResumableUploadError(
        "delivery_file_exists",
        "A delivery file with this name already exists.",
        409,
    )


def _discard_stale_assembly(chunks_descriptor: int) -> None:
    try:
        file_status = os.stat(
            ".assembled",
            dir_fd=chunks_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "Upload staging could not be inspected.",
            500,
        ) from exc
    if not stat.S_ISREG(file_status.st_mode):
        raise ResumableUploadError(
            "unsafe_upload_staging",
            "Upload staging is not safe.",
            500,
        )
    try:
        os.unlink(".assembled", dir_fd=chunks_descriptor)
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "Upload staging could not be prepared.",
            500,
        ) from exc


def _write_assembly(descriptor, chunk_paths, chunks_descriptor: int) -> None:
    try:
        output_descriptor = os.open(
            ".assembled",
            write_once_flags(),
            0o640,
            dir_fd=chunks_descriptor,
        )
        total_written = 0
        with os.fdopen(output_descriptor, "wb") as output:
            for chunk_number, chunk_path in enumerate(chunk_paths, start=1):
                expected_size = descriptor.expected_size_for_chunk(chunk_number)
                chunk_written = copy_regular_file_at(
                    chunks_descriptor,
                    chunk_path.name,
                    output,
                    max_bytes=expected_size,
                )
                if chunk_written != expected_size:
                    raise ResumableUploadError(
                        "invalid_upload_chunk_size",
                        "An upload chunk size differs from its declaration.",
                    )
                total_written += chunk_written
            output.flush()
            os.fsync(output.fileno())
        if total_written != descriptor.total_size:
            raise ResumableUploadError(
                "invalid_upload_size",
                "The uploaded data size differs from its declaration.",
            )
    except ResumableUploadError:
        raise
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "The uploaded delivery could not be assembled.",
            500,
        ) from exc


def _publish_assembly(paths, chunks_descriptor, target_directory) -> None:
    try:
        # A hard link publishes the regular file atomically and fails rather
        # than replacing an existing destination.
        os.link(
            ".assembled",
            paths.target_path.name,
            src_dir_fd=chunks_descriptor,
            dst_dir_fd=target_directory,
            follow_symlinks=False,
        )
        try:
            os.fsync(target_directory)
        except OSError:
            # The delivery is already atomically visible. Some supported
            # filesystems do not provide directory fsync.
            pass
    except FileExistsError as exc:
        raise _file_exists() from exc
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_error",
            "The uploaded delivery could not be assembled.",
            500,
        ) from exc


def _best_effort_unlink(directory_descriptor: int, filename: str) -> None:
    try:
        os.unlink(filename, dir_fd=directory_descriptor)
    except OSError:
        # Publication may already have succeeded. A stale private assembly is
        # cleaned on the next attempt; it must not create a false failure.
        pass


def _discard_published_chunks(chunks_descriptor, chunk_paths) -> None:
    for chunk_path in chunk_paths:
        try:
            os.unlink(chunk_path.name, dir_fd=chunks_descriptor)
        except FileNotFoundError:
            pass
        except OSError:
            # Publication already succeeded. A private stale chunk is safer
            # than returning a false failure that the client cannot retry.
            pass
