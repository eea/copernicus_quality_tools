"""Versioned artifact locations, independent of Django and worker imports."""

from dataclasses import dataclass
from pathlib import Path
import re

from .errors import JobStorageError
from .identifiers import compact_job_uuid, normalize_job_uuid


LEGACY_LAYOUT_VERSION = 1
CURRENT_LAYOUT_VERSION = 2
_CANONICAL = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_LEGACY = re.compile(r"job_([0-9a-f]{32})\Z")


def safe_artifact_name(value):
    if (not isinstance(value, str) or value in {"", ".", ".."}
            or Path(value).name != value or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise JobStorageError("Job artifact filename is unsafe.")
    return value


def job_uuid_from_directory_name(name):
    """Recognize only the two supported physical directory grammars."""
    if isinstance(name, str) and _CANONICAL.fullmatch(name):
        return normalize_job_uuid(name)
    match = _LEGACY.fullmatch(name) if isinstance(name, str) else None
    if match:
        return normalize_job_uuid(match.group(1))
    raise JobStorageError("Job directory name is not recognized.")


def recognize_job_directory(name):
    """Return a recognized directory identity, or None when scanning other files."""
    try:
        return job_uuid_from_directory_name(name)
    except JobStorageError:
        return None


@dataclass(frozen=True)
class JobPaths:
    jobs_root: Path
    job_uuid: str
    layout_version: int

    def __post_init__(self):
        root = Path(self.jobs_root)
        if not root.is_absolute() or ".." in root.parts or root == Path(root.anchor):
            raise JobStorageError("Job storage requires an absolute configured root.")
        if self.layout_version not in {LEGACY_LAYOUT_VERSION, CURRENT_LAYOUT_VERSION}:
            raise JobStorageError("Job storage layout is unsupported.")
        object.__setattr__(self, "jobs_root", root)
        object.__setattr__(self, "job_uuid", normalize_job_uuid(self.job_uuid))

    @property
    def legacy(self):
        return self.layout_version == LEGACY_LAYOUT_VERSION

    @property
    def directory(self):
        name = "job_" + compact_job_uuid(self.job_uuid) if self.legacy else self.job_uuid
        return self.jobs_root / name

    def _directory(self, name):
        path = self.directory / name if name else self.directory
        for item in (self.jobs_root, self.directory, path):
            if item.is_symlink() or (item.exists() and not item.is_dir()):
                raise JobStorageError("Job artifact directory is unsafe.")
        return path

    @property
    def metadata_path(self):
        return self.directory / "job.json"

    @property
    def result_path(self):
        return self.directory / "result.json"

    @property
    def specification_dir(self):
        return self._directory("" if self.legacy else "specification")

    @property
    def reports_dir(self):
        return self._directory("" if self.legacy else "reports")

    @property
    def output_dir(self):
        return self._directory("output.d" if self.legacy else "outputs")

    @property
    def logs_dir(self):
        return self._directory("" if self.legacy else "logs")

    @property
    def worker_log_path(self):
        return self.logs_dir / ("job.log" if self.legacy else "worker.log")

    @property
    def console_log_path(self):
        if self.legacy:
            return self.jobs_root / ("job." + self.job_uuid + ".stdout")
        return self.logs_dir / "console.log"

    def report_path(self, filename):
        return self.reports_dir / safe_artifact_name(filename)

    def specification_path(self, filename):
        return self.specification_dir / safe_artifact_name(filename)


def job_paths_for_layout(jobs_root, job_uuid, layout_version):
    """Construct paths for an explicitly owned creation/restore plan, without IO."""
    return JobPaths(Path(jobs_root), normalize_job_uuid(job_uuid), layout_version)
