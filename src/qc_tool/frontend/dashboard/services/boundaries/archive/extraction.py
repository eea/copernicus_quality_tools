"""Bounded extraction of already validated boundary archive members."""

from __future__ import annotations

import os
from pathlib import Path
import zlib
from zipfile import BadZipFile, ZipFile

from ..contracts import BoundaryPackageLimits, LIVE_DIRECTORY_NAMES
from ..errors import BoundaryPackageInvalid, BoundaryPackageLimitExceeded
from .constants import COPY_CHUNK_SIZE
from .validated import ValidatedArchive, ValidatedMember


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
        member_total, extracted_total = _extract_member(
            zip_file,
            member,
            destination,
            extracted_total,
            limits,
        )
        if member_total != member.info.file_size:
            raise BoundaryPackageInvalid("ZIP member size differs from its declaration")

    if extracted_total != archive.uncompressed_size:
        raise BoundaryPackageInvalid("ZIP total size differs from its declaration")


def _extract_member(
    zip_file: ZipFile,
    member: ValidatedMember,
    destination: Path,
    extracted_total: int,
    limits: BoundaryPackageLimits,
) -> tuple[int, int]:
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
                chunk = source.read(COPY_CHUNK_SIZE)
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
    return member_total, extracted_total


def _ensure_directory_tree(payload_dir: Path, destination: Path) -> None:
    """Create each validated staging directory with a group-readable mode."""

    current = payload_dir
    for part in destination.relative_to(payload_dir).parts:
        current /= part
        current.mkdir(mode=0o750, exist_ok=True)
        os.chmod(current, 0o750)
