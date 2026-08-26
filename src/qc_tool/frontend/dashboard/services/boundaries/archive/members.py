"""Validation of one boundary ZIP member and its normalized path."""

import stat
import unicodedata
from zipfile import ZipInfo

from ..contracts import BoundaryPackageLimits, LIVE_DIRECTORY_NAMES
from ..errors import (
    BoundaryPackageInvalid,
    BoundaryPackageLimitExceeded,
    BoundaryPackageUnsafe,
)
from .constants import SUPPORTED_COMPRESSION
from .validated import ValidatedMember


def validate_member(info: ZipInfo, limits: BoundaryPackageLimits) -> ValidatedMember:
    member = _validate_name(info, limits)
    _validate_type(info, member.is_directory)
    _validate_compression(info)
    _validate_size(info, limits)
    return member


def _validate_name(info: ZipInfo, limits: BoundaryPackageLimits) -> ValidatedMember:
    raw_name = info.filename
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise BoundaryPackageUnsafe("ZIP entry has an unsafe filename")
    if len(raw_name.encode("utf-8")) > limits.max_path_length:
        raise BoundaryPackageLimitExceeded("ZIP entry path is too long")

    normalized_name = unicodedata.normalize("NFC", raw_name)
    if normalized_name.startswith("/"):
        raise BoundaryPackageUnsafe("absolute ZIP paths are not accepted")
    if any(
        unicodedata.category(character) in ("Cc", "Cf")
        for character in normalized_name
    ):
        raise BoundaryPackageUnsafe("control characters are not accepted in ZIP paths")

    # Inspect lexical components because Path would silently collapse repeated
    # separators and ``.`` entries into a different destination.
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


def _validate_type(info: ZipInfo, is_directory: bool) -> None:
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise BoundaryPackageUnsafe("links and special filesystem entries are not accepted")
    if is_directory and file_type == stat.S_IFREG:
        raise BoundaryPackageUnsafe("ZIP directory has conflicting type metadata")
    if not is_directory and file_type == stat.S_IFDIR:
        raise BoundaryPackageUnsafe("ZIP file has conflicting type metadata")


def _validate_compression(info: ZipInfo) -> None:
    if info.flag_bits & 0x1:
        raise BoundaryPackageUnsafe("encrypted ZIP entries are not accepted")
    if info.compress_type not in SUPPORTED_COMPRESSION:
        raise BoundaryPackageUnsafe("unsupported ZIP compression method")


def _validate_size(info: ZipInfo, limits: BoundaryPackageLimits) -> None:
    if info.file_size < 0 or info.compress_size < 0:
        raise BoundaryPackageInvalid("ZIP entry has an invalid declared size")
    if info.file_size > limits.max_member_bytes:
        raise BoundaryPackageLimitExceeded("ZIP entry is too large")
