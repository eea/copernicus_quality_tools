"""Shared implementation limits for archive streaming."""

from zipfile import ZIP_DEFLATED, ZIP_STORED


COPY_CHUNK_SIZE = 1024 * 1024
SUPPORTED_COMPRESSION = frozenset((ZIP_STORED, ZIP_DEFLATED))
