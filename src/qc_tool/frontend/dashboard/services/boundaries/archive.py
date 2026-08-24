"""Bounded copying, validation, and extraction of boundary ZIP archives."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import stat
from typing import BinaryIO, Mapping, Optional, Union
import unicodedata
import zlib
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .contracts import BoundaryPackageLimits, LIVE_DIRECTORY_NAMES
from .errors import (
    BoundaryPackageInvalid,
    BoundaryPackageLimitExceeded,
    BoundaryPackageUnsafe,
)


_COPY_CHUNK_SIZE = 1024 * 1024
_SUPPORTED_COMPRESSION = frozenset((ZIP_STORED, ZIP_DEFLATED))


@dataclass(frozen=True)
class ValidatedMember:
    info: ZipInfo
    parts: tuple[str, ...]
    is_directory: bool


@dataclass(frozen=True)
class ValidatedArchive:
    members: tuple[ValidatedMember, ...]
    member_count: int
    file_count: int
    uncompressed_size: int


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
                chunk = source_stream.read(_COPY_CHUNK_SIZE)
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


def validate_archive(zip_file: ZipFile, limits: BoundaryPackageLimits) -> ValidatedArchive:
    """Validate the complete central directory without writing live data."""

    infos = zip_file.infolist()
    if not infos:
        raise BoundaryPackageInvalid("ZIP archive contains no entries")
    if len(infos) > limits.max_members:
        raise BoundaryPackageLimitExceeded("ZIP archive contains too many entries")

    validated: list[ValidatedMember] = []
    normalized_entries: dict[tuple[str, ...], bool] = {}
    total_size = 0
    total_compressed_size = 0
    file_count = 0

    for info in infos:
        member = _validate_member_name(info, limits)
        _validate_member_type(info, member.is_directory)

        if info.flag_bits & 0x1:
            raise BoundaryPackageUnsafe("encrypted ZIP entries are not accepted")
        if info.compress_type not in _SUPPORTED_COMPRESSION:
            raise BoundaryPackageUnsafe("unsupported ZIP compression method")
        if info.file_size < 0 or info.compress_size < 0:
            raise BoundaryPackageInvalid("ZIP entry has an invalid declared size")
        if info.file_size > limits.max_member_bytes:
            raise BoundaryPackageLimitExceeded("ZIP entry is too large")

        total_size += info.file_size
        total_compressed_size += info.compress_size
        if total_size > limits.max_uncompressed_bytes:
            raise BoundaryPackageLimitExceeded("ZIP expands beyond the total size limit")

        if not member.is_directory:
            file_count += 1
            _enforce_compression_ratio(
                info.file_size,
                info.compress_size,
                limits.max_compression_ratio,
            )

        normalized_key = tuple(part.casefold() for part in member.parts)
        if normalized_key in normalized_entries:
            raise BoundaryPackageUnsafe("ZIP contains duplicate normalized paths")
        normalized_entries[normalized_key] = member.is_directory
        validated.append(member)

    _validate_path_conflicts(normalized_entries)
    _enforce_compression_ratio(
        total_size,
        total_compressed_size,
        limits.max_compression_ratio,
    )
    if file_count == 0:
        raise BoundaryPackageInvalid("boundary package contains no files")

    return ValidatedArchive(
        members=tuple(validated),
        member_count=len(validated),
        file_count=file_count,
        uncompressed_size=total_size,
    )


def extract_archive(
    zip_file: ZipFile,
    archive: ValidatedArchive,
    payload_dir: Path,
    limits: BoundaryPackageLimits,
) -> None:
    """Extract validated regular files with fixed private permissions."""

    payload_dir.mkdir(mode=0o700)
    for directory_name in LIVE_DIRECTORY_NAMES:
        (payload_dir / directory_name).mkdir(mode=0o750)

    extracted_total = 0
    for member in archive.members:
        destination = payload_dir.joinpath(*member.parts)
        if member.is_directory:
            _ensure_directory_tree(payload_dir, destination)
            continue

        _ensure_directory_tree(payload_dir, destination.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        member_total = 0
        try:
            file_descriptor = os.open(destination, flags, 0o640)
            try:
                os.fchmod(file_descriptor, 0o640)
            except OSError:
                os.close(file_descriptor)
                raise
            with os.fdopen(file_descriptor, "wb") as output, zip_file.open(
                member.info, mode="r"
            ) as source:
                while True:
                    chunk = source.read(_COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    member_total += len(chunk)
                    extracted_total += len(chunk)
                    if member_total > limits.max_member_bytes:
                        raise BoundaryPackageLimitExceeded("extracted ZIP entry is too large")
                    if extracted_total > limits.max_uncompressed_bytes:
                        raise BoundaryPackageLimitExceeded("extracted ZIP is too large")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        except (BadZipFile, RuntimeError, zlib.error) as exc:
            raise BoundaryPackageInvalid("ZIP member integrity validation failed") from exc

        if member_total != member.info.file_size:
            raise BoundaryPackageInvalid("ZIP member size differs from its declaration")

    if extracted_total != archive.uncompressed_size:
        raise BoundaryPackageInvalid("ZIP total size differs from its declaration")


def _ensure_directory_tree(payload_dir: Path, destination: Path) -> None:
    """Create each validated staging directory with a group-readable mode."""

    current = payload_dir
    for part in destination.relative_to(payload_dir).parts:
        current /= part
        current.mkdir(mode=0o750, exist_ok=True)
        os.chmod(current, 0o750)


def _validate_member_name(info: ZipInfo, limits: BoundaryPackageLimits) -> ValidatedMember:
    raw_name = info.filename
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise BoundaryPackageUnsafe("ZIP entry has an unsafe filename")
    if len(raw_name.encode("utf-8")) > limits.max_path_length:
        raise BoundaryPackageLimitExceeded("ZIP entry path is too long")

    normalized_name = unicodedata.normalize("NFC", raw_name)
    if normalized_name.startswith("/"):
        raise BoundaryPackageUnsafe("absolute ZIP paths are not accepted")
    if any(unicodedata.category(character) in ("Cc", "Cf") for character in normalized_name):
        raise BoundaryPackageUnsafe("control characters are not accepted in ZIP paths")

    # Path objects collapse repeated separators and ``.``. Inspect the lexical
    # components so ambiguous names are rejected rather than silently remapped.
    lexical_name = normalized_name[:-1] if normalized_name.endswith("/") else normalized_name
    parts = tuple(lexical_name.split("/"))
    if not parts or len(parts) > limits.max_path_depth:
        raise BoundaryPackageLimitExceeded("ZIP entry path is too deep")
    if any(part in ("", ".", "..") for part in parts):
        raise BoundaryPackageUnsafe("relative ZIP path components are not accepted")
    if any(
        len(part.encode("utf-8")) > limits.max_path_component_bytes for part in parts
    ):
        raise BoundaryPackageLimitExceeded("ZIP path component is too long")
    if any(":" in part for part in parts):
        raise BoundaryPackageUnsafe("drive-qualified or alternate-stream paths are not accepted")
    if parts[0] not in LIVE_DIRECTORY_NAMES:
        raise BoundaryPackageUnsafe("ZIP entry is outside raster/vector roots")

    is_directory = info.is_dir()
    if len(parts) == 1 and not is_directory:
        raise BoundaryPackageUnsafe("raster/vector roots must be directories")
    return ValidatedMember(info=info, parts=parts, is_directory=is_directory)


def _validate_member_type(info: ZipInfo, is_directory: bool) -> None:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise BoundaryPackageUnsafe("links and special filesystem entries are not accepted")
    if is_directory and file_type == stat.S_IFREG:
        raise BoundaryPackageUnsafe("ZIP directory has conflicting type metadata")
    if not is_directory and file_type == stat.S_IFDIR:
        raise BoundaryPackageUnsafe("ZIP file has conflicting type metadata")


def _validate_path_conflicts(entries: Mapping[tuple[str, ...], bool]) -> None:
    for path in entries:
        for depth in range(1, len(path)):
            parent = path[:depth]
            if parent in entries and not entries[parent]:
                raise BoundaryPackageUnsafe("ZIP file is also used as a directory")


def _enforce_compression_ratio(
    uncompressed_size: int, compressed_size: int, maximum_ratio: float
) -> None:
    if uncompressed_size == 0:
        return
    if compressed_size == 0 or uncompressed_size / compressed_size > maximum_ratio:
        raise BoundaryPackageLimitExceeded("ZIP compression ratio exceeds the limit")
