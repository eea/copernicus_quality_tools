"""Stable facade for secure boundary ZIP processing."""

from .copying import copy_archive_bounded
from .extraction import extract_archive
from .validation import validate_archive
from .validated import ValidatedArchive, ValidatedMember


__all__ = (
    "ValidatedArchive",
    "ValidatedMember",
    "copy_archive_bounded",
    "extract_archive",
    "validate_archive",
)
