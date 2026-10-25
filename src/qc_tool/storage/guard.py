"""Fail closed on absent/wrong deployment storage without creating directories.

The operator provisions the root, application directories and identity marker.
A marker is an identity check, not evidence that the host's Azure mount is up;
the host must independently enforce mount availability before starting Docker.
"""

from contextlib import ExitStack, contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import uuid4


MARKER_NAME = ".qc-tool-storage-id"
MAX_MARKER_BYTES = 129
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class StorageConfigurationError(ValueError):
    """An operator-actionable storage readiness failure."""


def _absolute_path(value, name):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise StorageConfigurationError(f"{name} must name an existing absolute directory.")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise StorageConfigurationError(f"{name} must be an absolute directory without '..'.")
    return path


def _configuration(environment):
    root = _absolute_path(environment.get("QC_TOOL_PERSISTENT_STORAGE_ROOT"),
                          "QC_TOOL_PERSISTENT_STORAGE_ROOT")
    if root == Path("/"):
        raise StorageConfigurationError("The persistent storage root cannot be '/'.")
    identity = environment.get("QC_TOOL_PERSISTENT_STORAGE_ID", "")
    if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
        raise StorageConfigurationError("QC_TOOL_PERSISTENT_STORAGE_ID must contain 1-128 ASCII "
                                "letters, digits, periods, underscores or hyphens, "
                                "starting with a letter or digit.")
    directories = {}
    for name in ("WORK_DIR", "INCOMING_DIR", "BOUNDARY_DIR", "SUBMISSION_DIR"):
        value = environment.get(name)
        if name == "SUBMISSION_DIR" and not value:
            continue
        path = _absolute_path(value, name)
        if root not in path.parents:
            raise StorageConfigurationError(f"{name} must be a strict descendant of "
                                    "QC_TOOL_PERSISTENT_STORAGE_ROOT.")
        directories[name] = path
    return root, identity, directories


@contextmanager
def _directory(parts, *, parent=None):
    descriptor = os.open("/", _DIRECTORY_FLAGS) if parent is None else os.dup(parent)
    try:
        for part in parts:
            following = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    finally:
        os.close(descriptor)


def _check_marker(root_descriptor, identity):
    descriptor = os.open(MARKER_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=root_descriptor)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > MAX_MARKER_BYTES or before.st_mode & 0o022):
            raise StorageConfigurationError("The storage identity marker must be a bounded, "
                                    "single-link regular file without group/public write access.")
        payload = os.read(descriptor, MAX_MARKER_BYTES + 1)
        expected = identity.encode("ascii")
        if payload not in (expected, expected + b"\n"):
            raise StorageConfigurationError("The storage identity marker does not match "
                                    "QC_TOOL_PERSISTENT_STORAGE_ID. Check the mounted storage.")
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise StorageConfigurationError("The storage identity marker changed during the check.")
    finally:
        os.close(descriptor)


@contextmanager
def _checked_storage(environment):
    root, identity, directories = _configuration(environment)
    with ExitStack() as stack:
        try:
            root_descriptor = stack.enter_context(_directory(root.parts[1:]))
            _check_marker(root_descriptor, identity)
            for name, path in directories.items():
                try:
                    with _directory(path.relative_to(root).parts, parent=root_descriptor):
                        pass
                except OSError as error:
                    raise StorageConfigurationError(f"{name} is missing, inaccessible or contains "
                                            "a symbolic link. Provision it on the mounted storage.") from error
        except OSError as error:
            raise StorageConfigurationError("The configured storage root or identity marker is missing, "
                                    "inaccessible or contains a symbolic link. Mount and verify "
                                    "the intended storage; no directory or marker was created.") from error
        yield root, root_descriptor


def check_storage(environ=None):
    """Validate existing deployment storage without importing or writing app state."""
    with _checked_storage(os.environ if environ is None else environ) as (root, _descriptor):
        return root


_LOCK_PROBE = """
import fcntl, os, sys
descriptor = os.open('current', os.O_RDWR | os.O_NOFOLLOW, dir_fd=int(sys.argv[1]))
try:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = False
    except BlockingIOError:
        blocked = True
    sys.exit(0 if blocked == (sys.argv[2] == 'blocked') else 1)
finally:
    os.close(descriptor)
"""


def _check_process_lock(directory_descriptor, expected):
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", _LOCK_PROBE, str(directory_descriptor), expected],
            pass_fds=(directory_descriptor,), capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StorageConfigurationError("The independent-process filesystem locking probe failed.") from error
    if result.returncode:
        raise StorageConfigurationError("The filesystem does not provide the required "
                                "independent-process POSIX flock behavior.")


def _probe(directory_descriptor):
    for mode in (0o500, 0o700):
        os.fchmod(directory_descriptor, mode)
        if stat.S_IMODE(os.fstat(directory_descriptor).st_mode) != mode:
            raise StorageConfigurationError("The filesystem does not preserve private directory permission changes.")
    descriptor = os.open("staged", os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_descriptor)
    try:
        os.write(descriptor, b"qc-tool-filesystem-probe\n")
        for mode in (0o400, 0o600):
            os.fchmod(descriptor, mode)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != mode:
                raise StorageConfigurationError("The filesystem does not preserve private file permission changes.")
        os.fsync(descriptor)
        os.link("staged", "retained", src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor, follow_symlinks=False)
        linked = os.stat("retained", dir_fd=directory_descriptor, follow_symlinks=False)
        original = os.fstat(descriptor)
        if (linked.st_dev, linked.st_ino, linked.st_nlink) != (
                original.st_dev, original.st_ino, 2):
            raise StorageConfigurationError("The filesystem does not provide required hard-link semantics.")
        previous = os.open("current", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                           0o600, dir_fd=directory_descriptor)
        try:
            os.write(previous, b"previous probe state\n")
            os.fsync(previous)
        finally:
            os.close(previous)
        os.replace("staged", "current", src_dir_fd=directory_descriptor,
                   dst_dir_fd=directory_descriptor)
        current = os.open("current", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_descriptor)
        try:
            if os.read(current, 128) != b"qc-tool-filesystem-probe\n":
                raise StorageConfigurationError("The filesystem did not publish complete replacement bytes.")
        finally:
            os.close(current)
        os.symlink("current", "pointer", dir_fd=directory_descriptor)
        if os.readlink("pointer", dir_fd=directory_descriptor) != "current":
            raise StorageConfigurationError("The filesystem does not preserve symbolic links.")
        os.fsync(directory_descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _check_process_lock(directory_descriptor, "blocked")
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        _check_process_lock(directory_descriptor, "available")
    finally:
        os.close(descriptor)


def probe_storage(environment=None):
    """Explicit local syscall probe, confined to one disposable private directory.

    This does not certify network filesystem behavior between different clients,
    power-loss durability, persistence across redeployment or free-space capacity.
    """
    with _checked_storage(os.environ if environment is None else environment) as (root, root_descriptor):
        name = ".qc-tool-probe-" + uuid4().hex
        temporary_path = root / name
        try:
            os.mkdir(name, 0o700, dir_fd=root_descriptor)
        except OSError as error:
            raise StorageConfigurationError("Cannot create the private temporary filesystem probe directory.") from error
        try:
            with _directory((name,), parent=root_descriptor) as directory_descriptor:
                try:
                    _probe(directory_descriptor)
                except OSError as error:
                    raise StorageConfigurationError("The filesystem probe failed: file/directory fsync, "
                                            "hard links, symbolic links, atomic replacement, private "
                                            "permissions and POSIX flock are required.") from error
                finally:
                    for child in ("pointer", "current", "retained", "staged"):
                        try:
                            os.unlink(child, dir_fd=directory_descriptor)
                        except FileNotFoundError:
                            pass
        except OSError as error:
            raise StorageConfigurationError("The temporary filesystem probe could not complete or "
                                            f"clean up. Check its private directory: {temporary_path}") from error
        finally:
            try:
                os.rmdir(name, dir_fd=root_descriptor)
            except OSError as error:
                raise StorageConfigurationError("The filesystem probe could not remove its private "
                                                f"temporary directory: {temporary_path}") from error
