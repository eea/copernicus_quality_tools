"""Durable maintenance state and cross-process admission on shared storage.

Every frontend must use the same persistent directory on a filesystem with
working POSIX flock semantics. State survives DB outages and image restarts.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

from django.conf import settings

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.artifacts import open_regular_artifact, ArtifactUnavailable
from qc_tool.worker_auth import worker_maintenance_url


MAX_STATE_BYTES = 1024 * 1024
MAX_REGISTERED_WORKERS = 2048


class MaintenanceError(RuntimeError):
    """A safe operator-facing failure; admission remains closed on errors."""


def _directory():
    directory = Path(getattr(settings, "QC_TOOL_MAINTENANCE_DIR", CONFIG["work_dir"] / "maintenance"))
    created = False
    try:
        directory.mkdir(parents=True, mode=0o700)
        created = True
    except FileExistsError:
        pass
    status = directory.lstat()
    if not stat.S_ISDIR(status.st_mode) or status.st_mode & 0o022:
        raise MaintenanceError("Maintenance storage must be a real directory without group or public write access.")
    if created:
        # Only the exclusive directory creator may bootstrap OFF. An existing
        # directory with missing state is an error, never a new installation.
        write_status(_initial(), directory=directory)
        descriptor = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return directory


@contextmanager
def file_lock(name, *, exclusive=True, blocking=True):
    descriptor = None
    try:
        descriptor = os.open(_directory() / (name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o022:
            raise OSError("Unsafe maintenance lock file")
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, flags | (0 if blocking else fcntl.LOCK_NB))
            acquired = True
        except BlockingIOError:
            acquired = False
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise MaintenanceError("Maintenance storage or locking is unavailable. Contact the operator.") from exc
    try:
        # Keep caller exceptions outside the storage-error handler. A DB/file
        # error in the protected action must retain its actual ownership.
        yield acquired
    finally:
        os.close(descriptor)  # Closing also releases flock on all exit paths.


def _initial():
    return {"format_version": 1, "enabled": False, "phase": "off", "generation": 0,
            "blockers": [], "actor": "", "changed_at": "", "workers": [], "readiness_checked_at": ""}


def _validate_state(state):
    if not isinstance(state, dict):
        raise ValueError("Invalid maintenance state")
    # Accept the known pre-versioned format without rewriting it during reads.
    state = {"format_version": 1, "readiness_checked_at": "", **state}
    if (set(state) != set(_initial())
        or type(state["format_version"]) is not int or state["format_version"] != 1
        or type(state["enabled"]) is not bool
        or type(state["generation"]) is not int or state["generation"] < 0
        or state["phase"] not in {"off", "stopping", "ready"}
        or state["enabled"] != (state["phase"] != "off")
        or not isinstance(state["workers"], list) or len(state["workers"]) > MAX_REGISTERED_WORKERS
        or not all(isinstance(url, str) and len(url) <= 512 for url in state["workers"])
        or len(set(state["workers"])) != len(state["workers"])
        or not isinstance(state["blockers"], list) or len(state["blockers"]) > MAX_REGISTERED_WORKERS + 5
        or not all(isinstance(message, str) and len(message) <= 1024 for message in state["blockers"])
        or not isinstance(state["actor"], str) or len(state["actor"]) > 1024):
        raise ValueError("Invalid maintenance state")
    for key in ("changed_at", "readiness_checked_at"):
        value = state[key]
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("Invalid maintenance timestamp")
        if value and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Maintenance timestamps must include a timezone")
    for url in state["workers"]:
        worker_maintenance_url(url, expected_port=CONFIG.get("worker_port", 8000))
    return state


def read_status():
    try:
        path = _directory() / "state.json"
        with open_regular_artifact(path.parent, path.name) as handle:
            status = os.fstat(handle.fileno())
            if status.st_nlink != 1 or status.st_mode & 0o022:
                raise ValueError("Unsafe maintenance state file")
            raw = handle.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError
        state = _validate_state(json.loads(raw, object_pairs_hook=_unique_object))
        state["forced"] = bool(getattr(settings, "MAINTENANCE_MODE", False))
        state["environment_only"] = state["forced"] and not state["enabled"]
        if state["forced"] and not state["enabled"]:
            state.update(enabled=True, phase="stopping", generation=state["generation"] + 1,
                         blockers=["The environment forces maintenance. Check readiness to coordinate stopping."])
        return state
    except (ArtifactUnavailable, OSError, ValueError, TypeError) as exc:
        raise MaintenanceError("Maintenance state cannot be read. Contact the operator; application access remains blocked.") from exc


def _unique_object(pairs):
    """Ambiguous persisted authority must never be interpreted as OFF."""
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate maintenance state field")
        value[key] = item
    return value


def write_status(state, *, directory=None):
    # Caller owns control.lock. Readers always see a complete JSON document.
    data = _validate_state({key: value for key, value in state.items() if key not in {"forced", "environment_only"}})
    payload = json.dumps(data).encode()
    if len(payload) > MAX_STATE_BYTES:
        raise MaintenanceError("Maintenance state exceeds its storage limit.")
    directory = _directory() if directory is None else directory
    temp_path = None
    try:
        if (directory / "state.json").is_symlink():
            raise OSError("Unsafe maintenance state path")
        with tempfile.NamedTemporaryFile(mode="wb", dir=directory, delete=False) as handle:
            temp_path = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, directory / "state.json")
        temp_path = None
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise MaintenanceError("Maintenance state could not be saved. Contact the operator.") from exc
    finally:
        if temp_path is not None:
            Path(temp_path).unlink(missing_ok=True)


def stamp(state, actor):
    state.update(actor=str(actor), changed_at=datetime.now(timezone.utc).isoformat())


@contextmanager
def application_activity():
    """Hold a shared barrier through all request/response and background writes."""
    if read_status()["enabled"]:
        yield False
        return
    with file_lock("activity", exclusive=False, blocking=False) as acquired:
        yield acquired and not read_status()["enabled"]


def register_worker(worker_url):
    """Record workers before admitting claims; never write during a pause."""
    state = read_status()
    if not state["environment_only"] and (state["enabled"] or worker_url in state["workers"]):
        return state
    with file_lock("control"):
        state = read_status()
        if state["environment_only"]:
            write_status(state)
        if not state["enabled"] and worker_url not in state["workers"]:
            state["workers"].append(worker_url)
            write_status(state)
        return state
