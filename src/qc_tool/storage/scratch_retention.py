"""Explicit, reviewed removal of owned abandoned worker scratch only.

The caller must hold ready maintenance and verify the recorded job is terminal.
Unknown directories, debugging snapshots and links are never cleanup candidates.
This module has no authority over evidence, upload staging or recovery journals.
"""

from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import time
from uuid import UUID

from qc_tool.worker.scratch import process_namespace


META_FILENAME = ".qc-tool-scratch.json"
LEASE_FILENAME = ".lease"
MAX_ENTRIES = 100_000
MAX_METADATA_BYTES = 2048
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class ScratchRetentionError(ValueError):
    """Scratch remains retained until the operator resolves an unsafe state."""


def validate_scratch_layout(paths):
    """Require independently owned scratch, outside every durable namespace."""
    scratch = paths.scratch_dir
    if scratch is None:
        raise ScratchRetentionError("No separate scratch root is configured; legacy job directories are retained.")
    scratch = Path(scratch)
    protected = (paths.data_root, paths.jobs_dir, paths.incoming_dir, paths.boundaries_dir,
                 paths.submissions_dir, paths.specifications_dir, paths.shared_state_dir,
                 paths.frontend_state_dir, paths.transfer_dir, paths.backups_dir,
                 paths.logs_dir, paths.static_dir)
    for value in protected:
        if value is not None:
            path = Path(value)
            if scratch == path or scratch in path.parents or path in scratch.parents:
                raise ScratchRetentionError("Scratch overlaps durable application storage; cleanup is refused.")
    return scratch


def _fingerprint(status):
    return [status.st_dev, status.st_ino, status.st_mode, status.st_nlink,
            status.st_size, status.st_mtime_ns, status.st_ctime_ns]


@contextmanager
def _root(path):
    root = Path(path)
    if not root.is_absolute() or ".." in root.parts or root == Path("/"):
        raise ScratchRetentionError("Scratch requires a configured absolute root.")
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        for component in root.parts[1:]:
            following = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        if os.fstat(descriptor).st_mode & 0o022:
            raise ScratchRetentionError("Scratch root permits group/public writes; cleanup is refused.")
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(name):
    try:
        identifier = UUID(name)
    except (ValueError, AttributeError) as exc:
        raise ScratchRetentionError("Unrecognized scratch directory identity.") from exc
    if identifier.hex != name:
        raise ScratchRetentionError("Unrecognized scratch directory identity.")
    return str(identifier)


def _read_metadata(directory, identifier):
    descriptor = os.open(META_FILENAME, _FILE_FLAGS, dir_fd=directory)
    try:
        status = os.fstat(descriptor)
        if (not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
                or status.st_mode & 0o077 or status.st_size > MAX_METADATA_BYTES):
            raise ScratchRetentionError("Scratch ownership marker is unsafe.")
        raw = os.read(descriptor, MAX_METADATA_BYTES + 1)
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ScratchRetentionError("Scratch ownership marker has duplicate keys.")
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique)
        if (not isinstance(value, dict)
                or set(value) != {"format", "job_uuid", "retain", "owner_pid", "process_group", "pid_namespace"}
                or type(value["format"]) is not int or value["format"] != 1
                or value["job_uuid"] != identifier or type(value["retain"]) is not bool
                or not isinstance(value["pid_namespace"], str) or len(value["pid_namespace"]) > 256
                or any(type(value[key]) is not int or value[key] <= 0
                       for key in ("owner_pid", "process_group"))):
            raise ScratchRetentionError("Scratch ownership marker is unsupported.")
        return value
    finally:
        os.close(descriptor)


def _process_exists(identifier):
    try:
        os.kill(identifier, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _tree(directory, *, prefix="", entries=None):
    entries = {} if entries is None else entries
    device = os.fstat(directory).st_dev
    for name in sorted(os.listdir(directory)):
        key = prefix + name
        status = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if status.st_dev != device:
            raise ScratchRetentionError("Scratch contains a nested filesystem; retain it for review.")
        if len(entries) >= MAX_ENTRIES:
            raise ScratchRetentionError("Scratch inventory exceeds its bounded entry limit.")
        if stat.S_ISREG(status.st_mode):
            if status.st_nlink != 1:
                raise ScratchRetentionError("Scratch contains a hard-linked file; retain it for review.")
        elif stat.S_ISDIR(status.st_mode):
            if prefix.count("/") >= 32:
                raise ScratchRetentionError("Scratch inventory exceeds its path depth limit.")
        else:
            raise ScratchRetentionError("Scratch contains a link or special entry; retain it for review.")
        entries[key] = _fingerprint(status)
        if stat.S_ISDIR(status.st_mode):
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
            try:
                if _fingerprint(os.fstat(child)) != entries[key]:
                    raise ScratchRetentionError("Scratch changed during inventory.")
                _tree(child, prefix=key + "/", entries=entries)
            finally:
                os.close(child)
    return entries


@contextmanager
def _candidate(root, name):
    identifier = _identity(name)
    directory = os.open(name, _DIRECTORY_FLAGS, dir_fd=root)
    lease = None
    try:
        if os.fstat(directory).st_dev != os.fstat(root).st_dev:
            raise ScratchRetentionError("Scratch child is a nested filesystem; retain it for review.")
        if os.fstat(directory).st_mode & 0o077:
            raise ScratchRetentionError("Scratch directory must remain private (0700).")
        lease = os.open(LEASE_FILENAME, _FILE_FLAGS, dir_fd=directory)
        status = os.fstat(lease)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
            raise ScratchRetentionError("Scratch lease is unsafe.")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ScratchRetentionError("Scratch lease is active.") from exc
        metadata = _read_metadata(directory, identifier)
        if metadata["retain"]:
            raise ScratchRetentionError("Scratch was explicitly retained for debugging.")
        if metadata["pid_namespace"] != process_namespace():
            raise ScratchRetentionError("Scratch belongs to a different worker PID namespace; retain it for operator review.")
        if _process_exists(metadata["owner_pid"]) or _process_exists(-metadata["process_group"]):
            raise ScratchRetentionError("Scratch owner process or process group still exists.")
        yield directory, identifier, metadata
    finally:
        if lease is not None:
            os.close(lease)
        os.close(directory)


def _review(root, name, directory, metadata, minimum_age_seconds, now):
    if minimum_age_seconds < 3600:
        raise ScratchRetentionError("Scratch inactivity must be at least one hour.")
    entries = _tree(directory)
    status = os.fstat(directory)
    latest = max([status.st_mtime_ns, *(value[5] for value in entries.values())]) / 1e9
    if now - latest < minimum_age_seconds:
        raise ScratchRetentionError("Scratch has recent filesystem activity.")
    if _fingerprint(os.stat(name, dir_fd=root, follow_symlinks=False)) != _fingerprint(status):
        raise ScratchRetentionError("Scratch directory changed during review.")
    review = {"name": name, "directory": _fingerprint(status), "metadata": metadata, "entries": entries}
    token = sha256(json.dumps(review, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"job_uuid": metadata["job_uuid"], "eligible": True, "review_token": token,
            "entry_count": len(entries), "bytes": sum(value[4] for value in entries.values()
                                                    if stat.S_ISREG(value[2])),
            "inactive_hours": round((now - latest) / 3600, 1)}, entries


def inspect_scratch(scratch_root, *, minimum_age_seconds=86400, now=None):
    """Read-only bounded inventory; obtaining a lease never creates its file."""
    observed = time.time() if now is None else now
    results = []
    try:
        with _root(scratch_root) as root:
            names = sorted(os.listdir(root))
            if len(names) > MAX_ENTRIES:
                raise ScratchRetentionError("Scratch root exceeds its inventory entry limit.")
            for name in names:
                try:
                    with _candidate(root, name) as (directory, _identifier, metadata):
                        item, _entries = _review(root, name, directory, metadata, minimum_age_seconds, observed)
                except (OSError, ValueError, UnicodeError, RecursionError) as exc:
                    item = {"directory": name, "eligible": False,
                            "reason": str(exc) if isinstance(exc, ScratchRetentionError) else "Scratch ownership or storage could not be verified."}
                results.append(item)
    except FileNotFoundError:
        return []
    return results


def _remove_tree_contents(directory, entries, *, prefix=""):
    for name in sorted(os.listdir(directory)):
        if not prefix and name in {META_FILENAME, LEASE_FILENAME}:
            continue
        key = prefix + name
        status = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if key not in entries or _fingerprint(status) != entries[key]:
            raise ScratchRetentionError("Scratch changed after review; cleanup stopped.")
        if stat.S_ISDIR(status.st_mode):
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
            try:
                if _fingerprint(os.fstat(child)) != entries[key]:
                    raise ScratchRetentionError("Scratch changed after review; cleanup stopped.")
                _remove_tree_contents(child, entries, prefix=key + "/")
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=directory)
        else:
            os.unlink(name, dir_fd=directory)


def remove_scratch(scratch_root, job_uuid, review_token, *, minimum_age_seconds=86400, now=None):
    """Remove one exact reviewed scratch tree while caller holds ready maintenance."""
    name = UUID(str(job_uuid)).hex
    observed = time.time() if now is None else now
    with _root(scratch_root) as root, _candidate(root, name) as (directory, _identifier, metadata):
        review, entries = _review(root, name, directory, metadata, minimum_age_seconds, observed)
        if not review_token or review["review_token"] != review_token:
            raise ScratchRetentionError("Scratch changed or has no reviewed token. Plan cleanup again.")
        _remove_tree_contents(directory, entries)
        if set(os.listdir(directory)) != {META_FILENAME, LEASE_FILENAME}:
            raise ScratchRetentionError("Scratch changed during cleanup; ownership files retained.")
        for marker in (META_FILENAME, LEASE_FILENAME):
            if _fingerprint(os.stat(marker, dir_fd=directory, follow_symlinks=False)) != entries[marker]:
                raise ScratchRetentionError("Scratch ownership changed; cleanup stopped.")
        os.unlink(META_FILENAME, dir_fd=directory)
        os.unlink(LEASE_FILENAME, dir_fd=directory)
        os.fsync(directory)
        if os.stat(name, dir_fd=root, follow_symlinks=False).st_ino != os.fstat(directory).st_ino:
            raise ScratchRetentionError("Scratch directory changed; cleanup stopped.")
        os.rmdir(name, dir_fd=root)
        os.fsync(root)
    return {"job_uuid": str(UUID(str(job_uuid))), "removed": True, "bytes": review["bytes"]}
