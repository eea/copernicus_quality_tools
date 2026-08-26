"""Whole-archive validation and aggregate safety limits."""

from __future__ import annotations

from zipfile import ZipFile

from ..contracts import BoundaryPackageLimits
from ..errors import (
    BoundaryPackageInvalid,
    BoundaryPackageLimitExceeded,
    BoundaryPackageUnsafe,
)
from .members import validate_member
from .validated import ValidatedArchive, ValidatedMember


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
        member = validate_member(info, limits)

        total_size += info.file_size
        total_compressed_size += info.compress_size
        if total_size > limits.max_uncompressed_bytes:
            raise BoundaryPackageLimitExceeded("ZIP expands beyond the total size limit")

        if not member.is_directory:
            file_count += 1
            enforce_compression_ratio(
                info.file_size,
                info.compress_size,
                limits.max_compression_ratio,
            )

        normalized_key = tuple(part.casefold() for part in member.parts)
        if normalized_key in normalized_entries:
            raise BoundaryPackageUnsafe("ZIP contains duplicate normalized paths")
        normalized_entries[normalized_key] = member.is_directory
        validated.append(member)

    validate_path_conflicts(normalized_entries)
    enforce_compression_ratio(
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


def validate_path_conflicts(entries: dict[tuple[str, ...], bool]) -> None:
    for path in entries:
        for depth in range(1, len(path)):
            parent = path[:depth]
            if parent in entries and not entries[parent]:
                raise BoundaryPackageUnsafe("ZIP file is also used as a directory")


def enforce_compression_ratio(
    uncompressed_size: int, compressed_size: int, maximum_ratio: float
) -> None:
    if uncompressed_size == 0:
        return
    if compressed_size == 0 or uncompressed_size / compressed_size > maximum_ratio:
        raise BoundaryPackageLimitExceeded("ZIP compression ratio exceeds the limit")
