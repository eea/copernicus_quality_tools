"""Stable return contracts for S3 delivery materialization."""

from pathlib import Path


class S3DownloadResult:
    """Describe measured downloaded content without exposing credential state."""

    __slots__ = ("digest", "hash_files", "processing_dir", "original_zip_sha256")

    def __init__(self, *, digest, hash_files, processing_dir, original_zip_sha256=None):
        self.digest = digest
        self.hash_files = tuple(hash_files)
        self.processing_dir = Path(processing_dir)
        self.original_zip_sha256 = original_zip_sha256
