"""Immutable specification bytes and atomic activation/archive markers."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from time import monotonic, sleep

from .errors import CatalogError


@contextmanager
def staged_specification(work_dir, payload=b""):
    """Serialize upload publications and prepare complete bytes before DB writes."""

    directory = Path(work_dir) / "product_definitions"
    directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise OSError("Specification directory must be a real directory")
    _sync_directory(directory.parent)
    lock_fd = os.open(
        directory / ".upload.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    temporary_path = None
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise OSError("Specification lock must be a regular file")
        deadline = monotonic() + 5
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if monotonic() >= deadline:
                    raise CatalogError(
                        "specification_upload_busy",
                        "Another specification is being updated. Please retry shortly.",
                    )
                sleep(0.05)
        with tempfile.NamedTemporaryFile(
            prefix=".specification-", suffix=".tmp", dir=directory, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o644)
            os.fsync(temporary.fileno())
        yield directory, temporary_path
    finally:
        try:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        finally:
            os.close(lock_fd)


def validate_existing_file(target, payload):
    """Identical retries are allowed; never overwrite any existing target."""

    if target.is_symlink():
        raise OSError("Stored specification version must not be a symlink")
    if target.exists():
        if not target.is_file():
            raise OSError("Stored specification version must be a regular file")
        with target.open("rb") as source:
            if source.read(len(payload) + 1) != payload:
                raise OSError("Stored specification version has changed")


def publish_specification(staged, directory, ident, digest, payload):
    """Retain immutable bytes, then switch one atomic active-version pointer."""

    versions = directory / ".versions" / ident
    versions.mkdir(mode=0o755, parents=True, exist_ok=True)
    if versions.is_symlink() or versions.parent.is_symlink():
        raise OSError("Specification versions must be real directories")
    target = versions / (digest + ".json")
    try:
        os.link(staged, target)
    except FileExistsError:
        validate_existing_file(target, payload)
    _sync_directory(target.parent)
    _sync_directory(target.parent.parent)
    _sync_directory(directory)
    publish_specification_state(directory, ident, {"active": True, "digest": digest})


def publish_specification_state(directory, ident, state):
    states = directory / ".state"
    states.mkdir(mode=0o755, exist_ok=True)
    if states.is_symlink():
        raise OSError("Specification state directory must be a real directory")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".state-", dir=states, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(state).encode("utf-8"))
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o644)
            os.fsync(temporary.fileno())
        os.replace(temporary_path, states / (ident + ".json"))
        _sync_directory(states)
        _sync_directory(directory)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _sync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
