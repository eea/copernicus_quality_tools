"""Fail-closed errors for retained QC run storage."""


class JobStorageError(ValueError):
    """A job location or its provenance cannot be resolved safely."""
