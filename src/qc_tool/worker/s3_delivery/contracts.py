"""Stable return contracts for S3 delivery materialization."""

from pathlib import Path


class S3DownloadResult:
    """Describe a downloaded delivery without exposing credential state.

    This deliberately avoids newer dataclass features so the worker remains
    importable on its current Python 3.8 runtime.
    """

    __slots__ = ("digest", "hash_files", "processing_dir")

    def __init__(self, *, digest, hash_files, processing_dir):
        self.digest = digest
        self.hash_files = tuple(hash_files)
        self.processing_dir = Path(processing_dir)
