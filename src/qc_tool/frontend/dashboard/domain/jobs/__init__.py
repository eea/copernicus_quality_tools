"""QC job model and queue compatibility service."""

from .job import Job
from .queue import pull_job

__all__ = ("Job", "pull_job")
