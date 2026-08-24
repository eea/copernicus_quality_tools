"""No-follow, bounded extraction for untrusted ZIP archives."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
from typing import Mapping
import unicodedata
import zlib
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from .errors import UnsafeArchiveError
from .limits import ArchiveLimits


_COPY_CHUNK_SIZE = 1024 * 1024
_SUPPORTED_COMPRESSION = frozenset((ZIP_STORED, ZIP_DEFLATED))


@dataclass(frozen=True)
class _ValidatedMember:
    info: object
    parts: tuple
    is_directory: bool


def safely_extract_zip(archive_path, destination, limits=None):
    """Validate and extract one ZIP into a new private directory.

    Validation covers the complete central directory before the destination is
    created. Extraction still enforces the declared limits while streaming,
    because declarations in an untrusted archive cannot be trusted alone.
    """

    effective_limits = limits or ArchiveLimits.from_environment()
    archive_path = Path(archive_path)
    destination = Path(destination)
    try:
        archive_stat = archive_path.stat()
    except OSError as exc:
        raise UnsafeArchiveError("archive cannot be read") from exc
    if (
        archive_path.is_symlink()
        or not stat.S_ISREG(archive_stat.st_mode)
        or archive_stat.st_size <= 0
        or archive_stat.st_size > effective_limits.max_archive_bytes
    ):
        raise UnsafeArchiveError("archive path or size is unsafe")
    if destination.exists() or destination.is_symlink():
        raise UnsafeArchiveError("extraction destination already exists")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise UnsafeArchiveError("extraction parent is unsafe")

    try:
        with ZipFile(str(archive_path), mode="r", allowZip64=True) as zip_file:
            members, declared_total = _validate(zip_file, effective_limits)
            destination.mkdir(mode=0o700)
            _extract(
                zip_file,
                members,
                declared_total,
                destination,
                effective_limits,
            )
    except UnsafeArchiveError:
        _remove_destination(destination)
        raise
    except (BadZipFile, EOFError, RuntimeError, UnicodeError, ValueError, zlib.error) as exc:
        _remove_destination(destination)
        raise UnsafeArchiveError("ZIP parsing or integrity validation failed") from exc
    except OSError as exc:
        _remove_destination(destination)
        raise UnsafeArchiveError("archive extraction failed") from exc
    except Exception as exc:
        # A new parser failure mode must never leave a partially extracted
        # payload available to later QC steps.
        _remove_destination(destination)
        raise UnsafeArchiveError(
            "unexpected archive failure ({})".format(type(exc).__name__)
        ) from exc
    return destination


def _validate(zip_file, limits):
    infos = zip_file.infolist()
    if not infos or len(infos) > limits.max_members:
        raise UnsafeArchiveError("archive entry count is invalid")

    members = []
    normalized_entries = {}
    total_size = 0
    total_compressed = 0
    file_count = 0
    for info in infos:
        member = _validate_name(info, limits)
        _validate_type(info, member.is_directory)
        if info.flag_bits & 0x1:
            raise UnsafeArchiveError("encrypted entries are not accepted")
        if info.compress_type not in _SUPPORTED_COMPRESSION:
            raise UnsafeArchiveError("unsupported compression method")
        if info.file_size < 0 or info.compress_size < 0:
            raise UnsafeArchiveError("invalid declared member size")
        if info.file_size > limits.max_member_bytes:
            raise UnsafeArchiveError("member size limit exceeded")

        total_size += info.file_size
        total_compressed += info.compress_size
        if total_size > limits.max_uncompressed_bytes:
            raise UnsafeArchiveError("total expansion limit exceeded")
        if not member.is_directory:
            file_count += 1
            _enforce_ratio(
                info.file_size,
                info.compress_size,
                limits.max_compression_ratio,
            )

        normalized_key = tuple(part.casefold() for part in member.parts)
        if normalized_key in normalized_entries:
            raise UnsafeArchiveError("duplicate normalized archive path")
        normalized_entries[normalized_key] = member.is_directory
        members.append(member)

    _validate_path_conflicts(normalized_entries)
    _enforce_ratio(total_size, total_compressed, limits.max_compression_ratio)
    if file_count == 0:
        raise UnsafeArchiveError("archive contains no files")
    return tuple(members), total_size


def _extract(zip_file, members, declared_total, destination, limits):
    extracted_total = 0
    for member in members:
        target = destination.joinpath(*member.parts)
        if member.is_directory:
            _ensure_directories(destination, target)
            continue
        _ensure_directories(destination, target.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC

        member_total = 0
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output, zip_file.open(
            member.info,
            mode="r",
        ) as source:
            while True:
                chunk = source.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                member_total += len(chunk)
                extracted_total += len(chunk)
                if member_total > limits.max_member_bytes:
                    raise UnsafeArchiveError("member grew beyond its limit")
                if extracted_total > limits.max_uncompressed_bytes:
                    raise UnsafeArchiveError("archive grew beyond its limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if member_total != member.info.file_size:
            raise UnsafeArchiveError("member size differs from declaration")
    if extracted_total != declared_total:
        raise UnsafeArchiveError("archive size differs from declaration")


def _validate_name(info, limits):
    raw_name = info.filename
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise UnsafeArchiveError("unsafe archive filename")
    if len(raw_name.encode("utf-8")) > limits.max_path_bytes:
        raise UnsafeArchiveError("archive path is too long")

    normalized = unicodedata.normalize("NFC", raw_name)
    if normalized.startswith("/"):
        raise UnsafeArchiveError("absolute archive path")
    if any(
        unicodedata.category(character) in ("Cc", "Cf")
        for character in normalized
    ):
        raise UnsafeArchiveError("control character in archive path")
    lexical = normalized[:-1] if normalized.endswith("/") else normalized
    parts = tuple(lexical.split("/"))
    if not parts or len(parts) > limits.max_path_depth:
        raise UnsafeArchiveError("archive path depth is invalid")
    if any(part in ("", ".", "..") for part in parts):
        raise UnsafeArchiveError("relative archive component")
    if any(
        len(part.encode("utf-8")) > limits.max_component_bytes
        for part in parts
    ):
        raise UnsafeArchiveError("archive component is too long")
    if any(":" in part for part in parts):
        raise UnsafeArchiveError("drive or alternate-stream archive path")
    return _ValidatedMember(info, parts, info.is_dir())


def _validate_type(info, is_directory):
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise UnsafeArchiveError("link or special archive entry")
    if is_directory and file_type == stat.S_IFREG:
        raise UnsafeArchiveError("directory has file metadata")
    if not is_directory and file_type == stat.S_IFDIR:
        raise UnsafeArchiveError("file has directory metadata")


def _validate_path_conflicts(entries: Mapping):
    for path in entries:
        for depth in range(1, len(path)):
            parent = path[:depth]
            if parent in entries and not entries[parent]:
                raise UnsafeArchiveError("archive file is also a directory")


def _ensure_directories(root, target):
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            if current.is_symlink() or not current.is_dir():
                raise UnsafeArchiveError("unsafe extraction directory")
        if current.is_symlink():
            raise UnsafeArchiveError("link in extraction directory")
        os.chmod(current, 0o700)


def _enforce_ratio(uncompressed_size, compressed_size, maximum_ratio):
    if uncompressed_size == 0:
        return
    if compressed_size == 0 or uncompressed_size / compressed_size > maximum_ratio:
        raise UnsafeArchiveError("compression ratio limit exceeded")


def _remove_destination(destination):
    if destination.is_symlink():
        destination.unlink(missing_ok=True)
    elif destination.exists():
        shutil.rmtree(destination)
