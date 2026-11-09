"""Confined mixed-layout resolution and explicit creation of new run storage."""

import os

from .context import initial_job_context, read_job_context, write_job_context
from .errors import JobStorageError
from .paths import CURRENT_LAYOUT_VERSION, LEGACY_LAYOUT_VERSION, job_paths_for_layout


def resolve_job_paths(jobs_root, job_uuid, *, require_exists=False):
    """Select one exact namespace, refusing collisions and unsafe directories."""
    current = job_paths_for_layout(jobs_root, job_uuid, CURRENT_LAYOUT_VERSION)
    legacy = job_paths_for_layout(jobs_root, job_uuid, LEGACY_LAYOUT_VERSION)
    if current.jobs_root.is_symlink() or (current.jobs_root.exists() and not current.jobs_root.is_dir()):
        raise JobStorageError("Job storage root is unsafe.")
    existing = [paths for paths in (current, legacy) if os.path.lexists(paths.directory)]
    if len(existing) > 1:
        raise JobStorageError("Both job storage layouts exist for this identity.")
    if not existing:
        if require_exists:
            raise JobStorageError("The retained job directory is unavailable.")
        return current
    paths = existing[0]
    if paths.directory.is_symlink() or not paths.directory.is_dir():
        raise JobStorageError("Job storage directory is unsafe.")
    if not paths.legacy:
        read_job_context(paths)
    return paths


def create_job_paths(jobs_root, job_uuid, *, exist_ok=False):
    """Create canonical storage, or reuse only an explicitly prepared empty run."""
    paths = resolve_job_paths(jobs_root, job_uuid)
    if os.path.lexists(paths.directory):
        if paths.legacy or not exist_ok:
            raise FileExistsError("A retained job already owns this identity.")
        context = read_job_context(paths)
        if paths.result_path.exists() or context["execution"]["status"] not in {None, "queued"}:
            raise JobStorageError("This job has already started; choose a new run identity.")
        return paths
    paths.jobs_root.mkdir(parents=True, exist_ok=True)
    paths.directory.mkdir(mode=0o750)
    # A crash during preparation leaves an unrecognized partial canonical run.
    # Never remove or adopt it automatically on the next attempt.
    for directory in (paths.specification_dir, paths.reports_dir, paths.output_dir, paths.logs_dir):
        directory.mkdir(mode=0o750)
    write_job_context(paths, initial_job_context(paths))
    return paths
