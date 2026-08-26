"""Validated archive value objects shared by validation and extraction."""

from __future__ import annotations

from dataclasses import dataclass
from zipfile import ZipInfo


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
