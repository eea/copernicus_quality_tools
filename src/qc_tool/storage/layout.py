"""Configured runtime roots and access to versioned job artifact locations.

``QC_TOOL_DATA_ROOT`` explicitly selects the canonical layout. Without it the
historical environment and path contracts remain in force. Constructing roots
never creates or moves files. Job-specific resolution checks only the two
supported directory names beneath the configured jobs root.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from qc_tool.jobs import compact_job_uuid, resolve_job_paths


def _optional_path(value):
    return Path(value) if value not in (None, "") else None


def layout_config(environment=None, *, test_data_dir=None):
    """Read the path environment once for the application's configuration dict."""
    environment = os.environ if environment is None else environment
    data_root = _optional_path(environment.get("QC_TOOL_DATA_ROOT"))
    config = {"data_root": data_root}
    defaults = {
        "WORK_DIR": ("work_dir", data_root / "jobs" if data_root else Path("/mnt/qc_tool_volume/work")),
        "INCOMING_DIR": ("incoming_dir", data_root / "incoming" if data_root else test_data_dir),
        "BOUNDARY_DIR": ("boundary_dir", data_root / "boundaries" if data_root else Path("/mnt/qc_tool_boundary/boundaries")),
        "SUBMISSION_DIR": ("submission_dir", data_root / "submissions" if data_root else None),
        "QC_TOOL_SPECIFICATIONS_DIR": ("specifications_dir", data_root / "specifications" if data_root else None),
        "QC_TOOL_SHARED_STATE_DIR": ("shared_state_dir", data_root.parent / "state" / "shared" if data_root else None),
        "QC_TOOL_FRONTEND_STATE_DIR": ("frontend_state_dir", Path("/var/lib/qc_tool") if data_root else None),
        "QC_TOOL_SCRATCH_DIR": ("scratch_dir", Path("/var/tmp/qc-tool/jobs") if data_root else None),
        "QC_TOOL_LOG_DIR": ("log_dir", Path("/var/log/qc-tool") if data_root else None),
        "QC_TOOL_TRANSFER_DIR": ("transfer_dir", None),
        "QC_TOOL_UPLOAD_TEMP_DIR": ("upload_temp_dir", None),
        "QC_TOOL_BACKUPS_DIR": ("backups_dir", None),
        "DJANGO_STATIC_ROOT": ("static_dir", None),
    }
    for name, (key, default) in defaults.items():
        if name in environment:
            config[key] = _optional_path(environment[name])
        elif default is not None or key == "submission_dir":
            config[key] = default
    return config


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved ownership roots; all locations come from the supplied config."""

    data_root: Path | None
    jobs_dir: Path
    incoming_dir: Path
    boundaries_dir: Path
    submissions_dir: Path | None
    specifications_dir: Path
    shared_state_dir: Path
    frontend_state_dir: Path
    transfer_dir: Path
    upload_temp_dir: Path | None
    backups_dir: Path
    logs_dir: Path
    scratch_dir: Path | None
    static_dir: Path
    announcement_path: Path

    @property
    def canonical(self):
        return self.data_root is not None

    @property
    def worker_token_path(self):
        return self.shared_state_dir / "worker.token"

    @property
    def maintenance_dir(self):
        return self.shared_state_dir / "maintenance"

    def job_paths(self, job_uuid, *, require_exists=False):
        return resolve_job_paths(self.jobs_dir, job_uuid, require_exists=require_exists)

    def job_dir(self, job_uuid):
        return self.job_paths(job_uuid).directory

    def job_stdout_path(self, job_uuid):
        return self.job_paths(job_uuid).console_log_path

    def job_scratch_dir(self, job_uuid):
        if self.scratch_dir is None:
            paths = self.job_paths(job_uuid)
            if paths.legacy:
                return paths.directory / "tmp.d"
            return Path("/var/tmp/qc-tool/jobs") / compact_job_uuid(job_uuid)
        return self.scratch_dir / compact_job_uuid(job_uuid)


def runtime_paths(config: Mapping):
    """Derive paths on demand, so explicit config overrides remain authoritative.

    Legacy fallbacks deliberately use the current ``work_dir`` and database
    path rather than cached module-level defaults. This also supports isolated
    operator/test configurations without probing another deployment's files.
    """
    data_root = _optional_path(config.get("data_root"))
    canonical = data_root is not None
    jobs = Path(config["work_dir"])
    frontend = _optional_path(config.get("frontend_state_dir")) or Path(
        config.get("frontend_db_path", "/var/lib/qc_tool/frontend.sqlite3")
    ).parent
    shared = _optional_path(config.get("shared_state_dir")) or (
        data_root.parent / "state" / "shared" if canonical else jobs
    )
    specifications = _optional_path(config.get("specifications_dir")) or (
        data_root / "specifications" if canonical else jobs / "product_definitions"
    )
    return RuntimePaths(
        data_root=data_root,
        jobs_dir=jobs,
        incoming_dir=Path(config.get("incoming_dir", data_root / "incoming" if canonical else jobs / "incoming")),
        boundaries_dir=Path(config.get("boundary_dir", data_root / "boundaries" if canonical else jobs / "boundaries")),
        submissions_dir=_optional_path(config.get("submission_dir")),
        specifications_dir=specifications,
        shared_state_dir=shared,
        frontend_state_dir=frontend,
        transfer_dir=_optional_path(config.get("transfer_dir")) or (frontend / "data-transfer" if canonical else jobs / "data-transfer"),
        upload_temp_dir=_optional_path(config.get("upload_temp_dir")) or (frontend / "upload-staging" if canonical else None),
        backups_dir=_optional_path(config.get("backups_dir")) or frontend / "backups",
        logs_dir=_optional_path(config.get("log_dir")) or (Path("/var/log/qc-tool") if canonical else jobs),
        scratch_dir=_optional_path(config.get("scratch_dir")) or (Path("/var/tmp/qc-tool/jobs") if canonical else None),
        static_dir=_optional_path(config.get("static_dir")) or frontend / "static",
        announcement_path=frontend / "announcement.txt",
    )
