"""Safe access to files returned by dashboard responses."""

from .errors import ArtifactUnavailable
from .files import open_job_attachment
from .files import open_job_report
from .files import open_regular_artifact
from .files import read_text_artifact


__all__ = (
    "ArtifactUnavailable",
    "open_job_attachment",
    "open_job_report",
    "open_regular_artifact",
    "read_text_artifact",
)
