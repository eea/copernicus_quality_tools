"""Validated metadata for one Resumable.js delivery upload."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from .errors import ResumableUploadError


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,200}\Z", re.ASCII)
_POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]{0,11}\Z", re.ASCII)
_MAX_CHUNKS = 25_000
MAX_CHUNK_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 100 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ResumableUploadDescriptor:
    identifier: str
    filename: str
    chunk_number: int
    chunk_size: int
    current_chunk_size: int
    total_chunks: int
    total_size: int

    @classmethod
    def from_mapping(cls, values) -> "ResumableUploadDescriptor":
        identifier = _single_mapping_value(values, "resumableIdentifier")
        filename = _single_mapping_value(values, "resumableFilename")
        if not isinstance(identifier, str) or not _IDENTIFIER_PATTERN.fullmatch(
            identifier
        ):
            raise ResumableUploadError(
                "invalid_upload_identifier",
                "The upload identifier is invalid.",
            )
        _validate_filename(filename)

        chunk_number = _positive_integer(
            _single_mapping_value(values, "resumableChunkNumber")
        )
        chunk_size = _positive_integer(
            _single_mapping_value(values, "resumableChunkSize")
        )
        current_chunk_size = _positive_integer(
            _single_mapping_value(values, "resumableCurrentChunkSize")
        )
        total_chunks = _positive_integer(
            _single_mapping_value(values, "resumableTotalChunks")
        )
        total_size = _positive_integer(
            _single_mapping_value(values, "resumableTotalSize")
        )
        _validate_bounds(
            chunk_number=chunk_number,
            chunk_size=chunk_size,
            current_chunk_size=current_chunk_size,
            total_chunks=total_chunks,
            total_size=total_size,
        )
        _validate_layout(
            chunk_number=chunk_number,
            chunk_size=chunk_size,
            current_chunk_size=current_chunk_size,
            total_chunks=total_chunks,
            total_size=total_size,
        )

        return cls(
            identifier=identifier,
            filename=filename,
            chunk_number=chunk_number,
            chunk_size=chunk_size,
            current_chunk_size=current_chunk_size,
            total_chunks=total_chunks,
            total_size=total_size,
        )

    @property
    def storage_key(self) -> str:
        """Return an opaque key bound to all upload-wide metadata."""

        metadata = "\0".join(
            (
                self.identifier,
                self.filename,
                str(self.chunk_size),
                str(self.total_chunks),
                str(self.total_size),
            )
        ).encode("utf-8")
        return sha256(metadata).hexdigest()

    def expected_size_for_chunk(self, chunk_number: int) -> int:
        if chunk_number < 1 or chunk_number > self.total_chunks:
            raise ValueError("chunk number is outside the upload")
        if chunk_number < self.total_chunks:
            return self.chunk_size
        return self.total_size - self.chunk_size * (self.total_chunks - 1)


def _single_mapping_value(values, name: str):
    getlist = getattr(values, "getlist", None)
    if callable(getlist):
        candidates = getlist(name)
        if len(candidates) != 1:
            raise _invalid_parameters()
        return candidates[0]
    try:
        return values.get(name)
    except AttributeError as exc:
        raise _invalid_parameters() from exc


def _positive_integer(value) -> int:
    if isinstance(value, bool):
        value = None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        text = ""
    if not _POSITIVE_INTEGER_PATTERN.fullmatch(text):
        raise _invalid_parameters()
    return int(text)


def _invalid_parameters() -> ResumableUploadError:
    return ResumableUploadError(
        "invalid_upload_parameters",
        "The upload parameters are invalid.",
    )


def _validate_filename(filename) -> None:
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise ResumableUploadError(
            "invalid_delivery_filename",
            "The delivery filename is invalid.",
        )
    try:
        encoded_length = len(filename.encode("utf-8"))
    except UnicodeError as exc:
        raise ResumableUploadError(
            "invalid_delivery_filename",
            "The delivery filename is invalid.",
        ) from exc
    path = Path(filename)
    if (
        path.name != filename
        or "\\" in filename
        or filename in {".", ".."}
        or any(ord(character) < 32 for character in filename)
        or encoded_length > 255
        or path.suffix.lower() != ".zip"
    ):
        raise ResumableUploadError(
            "invalid_delivery_filename",
            "The delivery filename must be a plain .zip filename.",
        )


def _validate_bounds(
    *,
    chunk_number: int,
    chunk_size: int,
    current_chunk_size: int,
    total_chunks: int,
    total_size: int,
) -> None:
    if total_chunks > _MAX_CHUNKS or chunk_number > total_chunks:
        raise ResumableUploadError(
            "invalid_chunk_number",
            "The upload chunk numbers are invalid.",
        )
    if total_size > _MAX_TOTAL_BYTES:
        raise ResumableUploadError(
            "delivery_too_large",
            "The delivery exceeds the configured upload size limit.",
            413,
        )
    if chunk_size > MAX_CHUNK_BYTES or current_chunk_size > MAX_CHUNK_BYTES:
        raise ResumableUploadError(
            "upload_chunk_too_large",
            "The upload chunk exceeds the configured size limit.",
            413,
        )


def _validate_layout(
    *,
    chunk_number: int,
    chunk_size: int,
    current_chunk_size: int,
    total_chunks: int,
    total_size: int,
) -> None:
    # This is the layout produced by the bundled Resumable.js client with
    # forceChunkSize=false. Binding requests to it prevents metadata mixing.
    expected_total_chunks = max(total_size // chunk_size, 1)
    expected_current_size = total_size - chunk_size * (total_chunks - 1)
    if chunk_number < total_chunks:
        expected_current_size = chunk_size
    if (
        total_chunks != expected_total_chunks
        or current_chunk_size != expected_current_size
    ):
        raise ResumableUploadError(
            "invalid_chunk_layout",
            "The upload chunk layout is invalid.",
        )
