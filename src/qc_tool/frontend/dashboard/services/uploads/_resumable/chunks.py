"""Atomic storage and safe probing of individual upload chunks."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from secrets import token_hex
import os

from .descriptor import MAX_CHUNK_BYTES, ResumableUploadDescriptor
from .errors import ResumableUploadError
from .filesystem import hash_regular_file_at
from .filesystem import open_directory
from .filesystem import regular_file_exists
from .filesystem import write_once_flags
from .paths import ResumableUploadPaths, expected_chunk_paths


def store_chunk(
    uploaded_file,
    destination: Path,
    *,
    expected_bytes: int | None = None,
    max_chunk_bytes: int = MAX_CHUNK_BYTES,
) -> bool:
    """Atomically store a chunk; identical retries are idempotent."""

    if uploaded_file is None:
        raise ResumableUploadError(
            "missing_upload_chunk",
            "The upload chunk is required.",
        )
    _validate_size_limits(expected_bytes, max_chunk_bytes)
    _validate_advertised_size(uploaded_file, expected_bytes, max_chunk_bytes)

    temporary_name = f".{destination.name}.{token_hex(16)}.uploading"
    byte_count = 0
    digest = sha256()
    directory_descriptor = open_directory(destination.parent)
    try:
        try:
            file_descriptor = os.open(
                temporary_name,
                write_once_flags(),
                0o600,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            raise ResumableUploadError(
                "upload_storage_error",
                "The upload chunk could not be stored.",
                500,
            ) from exc

        with os.fdopen(file_descriptor, "wb") as output:
            for chunk in uploaded_file.chunks():
                if not isinstance(chunk, bytes):
                    raise ResumableUploadError(
                        "invalid_upload_chunk",
                        "The upload chunk is invalid.",
                    )
                byte_count += len(chunk)
                if byte_count > max_chunk_bytes:
                    raise ResumableUploadError(
                        "upload_chunk_too_large",
                        "The upload chunk exceeds the configured size limit.",
                        413,
                    )
                digest.update(chunk)
                output.write(chunk)
            _validate_actual_size(byte_count, expected_bytes)
            output.flush()
            os.fsync(output.fileno())

        try:
            os.link(
                temporary_name,
                destination.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            try:
                os.fsync(directory_descriptor)
            except OSError:
                # Some filesystems do not support directory fsync. The chunk
                # is already atomically visible and can be probed/retried.
                pass
            return True
        except FileExistsError:
            existing_size, existing_digest = hash_regular_file_at(
                directory_descriptor,
                destination.name,
                max_bytes=max_chunk_bytes,
            )
            if existing_size == byte_count and existing_digest == digest.digest():
                return False
            raise ResumableUploadError(
                "duplicate_chunk_conflict",
                "This upload chunk was already stored with different content.",
                409,
            )
        except OSError as exc:
            raise ResumableUploadError(
                "upload_storage_error",
                "The upload chunk could not be stored.",
                500,
            ) from exc
    finally:
        try:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ResumableUploadError(
                "upload_storage_error",
                "Upload staging could not be cleaned up.",
                500,
            ) from exc
        finally:
            os.close(directory_descriptor)


def is_chunk_stored(destination: Path) -> bool:
    return regular_file_exists(destination)


def is_upload_complete(
    descriptor: ResumableUploadDescriptor,
    paths: ResumableUploadPaths,
) -> bool:
    return all(
        regular_file_exists(path)
        for path in expected_chunk_paths(descriptor, paths)
    )


def _validate_size_limits(expected_bytes, max_chunk_bytes) -> None:
    if (
        isinstance(max_chunk_bytes, bool)
        or not isinstance(max_chunk_bytes, int)
        or max_chunk_bytes <= 0
    ):
        raise ValueError("max_chunk_bytes must be a positive integer")
    if expected_bytes is not None and (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
        or expected_bytes > max_chunk_bytes
    ):
        raise ValueError(
            "expected_bytes must be a positive integer within max_chunk_bytes"
        )


def _validate_advertised_size(uploaded_file, expected_bytes, max_bytes) -> None:
    advertised_size = getattr(uploaded_file, "size", None)
    if isinstance(advertised_size, int) and advertised_size > max_bytes:
        raise ResumableUploadError(
            "upload_chunk_too_large",
            "The upload chunk exceeds the configured size limit.",
            413,
        )
    if (
        expected_bytes is not None
        and isinstance(advertised_size, int)
        and advertised_size != expected_bytes
    ):
        raise ResumableUploadError(
            "invalid_upload_chunk_size",
            "The upload chunk size differs from its declaration.",
        )


def _validate_actual_size(byte_count: int, expected_bytes: int | None) -> None:
    if byte_count == 0:
        raise ResumableUploadError(
            "empty_upload_chunk",
            "The upload chunk is empty.",
        )
    if expected_bytes is not None and byte_count != expected_bytes:
        raise ResumableUploadError(
            "invalid_upload_chunk_size",
            "The upload chunk size differs from its declaration.",
        )
