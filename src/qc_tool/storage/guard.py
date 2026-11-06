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

from .layout import layout_config, runtime_paths


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


def layout_roots(environment):
    """Return the exact mounts owned by one separated-layout service role."""
    role = environment.get("QC_TOOL_STORAGE_ROLE")
    if role not in {"frontend", "worker"}:
        raise StorageConfigurationError("QC_TOOL_STORAGE_ROLE must be frontend or worker.")
    config = layout_config(environment)
    paths = runtime_paths(config)
    data = _absolute_path(str(paths.data_root or ""), "QC_TOOL_DATA_ROOT")
    roots = {
        "incoming": (paths.incoming_dir, role == "frontend"),
        "boundaries": (paths.boundaries_dir, role == "frontend"),
        "specifications": (paths.specifications_dir, role == "frontend"),
        "jobs": (paths.jobs_dir, True),
        "shared-state": (paths.shared_state_dir, True),
        "logs": (paths.logs_dir, True),
    }
    if role == "frontend":
        if paths.submissions_dir is not None:
            roots["submissions"] = (paths.submissions_dir, True)
        roots["frontend-state"] = (paths.frontend_state_dir, True)
    else:
        roots["scratch"] = (paths.scratch_dir, True)
    for name, (configured, _writable) in roots.items():
        path = _absolute_path(str(configured or ""), name)
        if path == Path("/"):
            raise StorageConfigurationError(f"{name} cannot use the filesystem root.")
        if name in {"incoming", "boundaries", "specifications", "jobs", "submissions"} and data not in path.parents:
            raise StorageConfigurationError(f"{name} must be below QC_TOOL_DATA_ROOT.")
        for other, (other_path, _) in roots.items():
            if other != name and other_path is not None and (path == other_path or path in other_path.parents or other_path in path.parents):
                raise StorageConfigurationError(f"Storage mounts {name} and {other} must not overlap.")
    return data, roots


def check_layout(environment=None, *, require_identity=False):
    """Validate provisioned role mounts before any Django or worker writes."""
    environment = os.environ if environment is None else environment
    root, roots = layout_roots(environment)
    _validate_private_paths(environment)
    identity = environment.get("QC_TOOL_PERSISTENT_STORAGE_ID", "")
    if require_identity and not _IDENTITY.fullmatch(identity):
        raise StorageConfigurationError("QC_TOOL_PERSISTENT_STORAGE_ID requires a valid storage identity.")
    require_mounts = environment.get("QC_TOOL_REQUIRE_MOUNTS", "no")
    if require_mounts not in {"yes", "no"}:
        raise StorageConfigurationError("QC_TOOL_REQUIRE_MOUNTS must be yes or no.")
    try:
        for name, (path, _writable) in roots.items():
            with _directory(path.parts[1:]) as descriptor:
                if require_mounts == "yes" and not os.path.ismount(path):
                    raise StorageConfigurationError(f"{name} is not mounted at its configured root: {path}")
                if require_identity:
                    _check_marker(descriptor, identity)
    except OSError as error:
        raise StorageConfigurationError("A required storage mount is missing, inaccessible or contains a symbolic link; no fallback was created.") from error
    return root


def _validate_private_paths(environment):
    paths = runtime_paths(layout_config(environment))
    if environment.get("QC_TOOL_STORAGE_ROLE") == "frontend":
        private = paths.frontend_state_dir
        children = {"transfer": paths.transfer_dir, "backups": paths.backups_dir,
                    "upload spool": paths.upload_temp_dir, "static": paths.static_dir,
                    "credentials": Path(environment.get("S3_CREDENTIALS_DIR") or private / "s3_credentials")}
        for name, path in children.items():
            if path is None or not path.is_absolute() or ".." in path.parts or private not in path.parents:
                raise StorageConfigurationError(f"The {name} path must be a strict descendant of frontend-private storage.")
            for other, other_path in children.items():
                if other != name and other_path is not None and (path == other_path or path in other_path.parents or other_path in path.parents):
                    raise StorageConfigurationError(f"Private {name} and {other} storage must not overlap.")
        sqlite = Path(environment.get("FRONTEND_DB_PATH") or private / "frontend.sqlite3")
        if not sqlite.is_absolute() or ".." in sqlite.parts or private not in sqlite.parents:
            raise StorageConfigurationError("Frontend SQLite storage must be below frontend-private storage.")
        if any(sqlite == path or path in sqlite.parents or sqlite in path.parents for path in children.values()):
            raise StorageConfigurationError("Frontend SQLite storage must not overlap static files or other private service directories.")
    maintenance = Path(environment.get("QC_TOOL_MAINTENANCE_DIR") or paths.maintenance_dir)
    if not maintenance.is_absolute() or ".." in maintenance.parts or paths.shared_state_dir not in maintenance.parents:
        raise StorageConfigurationError("Maintenance storage must be below the shared-state mount.")


def prepare_frontend(environment=None):
    """Provision only private children of an already validated frontend mount."""
    environment = os.environ if environment is None else environment
    if environment.get("QC_TOOL_STORAGE_ROLE") != "frontend":
        raise StorageConfigurationError("Private frontend preparation requires the frontend storage role.")
    check_layout(environment, require_identity=bool(environment.get("QC_TOOL_PERSISTENT_STORAGE_ID")))
    paths = runtime_paths(layout_config(environment))
    children = (paths.upload_temp_dir, paths.transfer_dir, paths.backups_dir, paths.static_dir,
                Path(environment.get("S3_CREDENTIALS_DIR") or paths.frontend_state_dir / "s3_credentials"))
    with _directory(paths.frontend_state_dir.parts[1:]) as root:
        for path in children:
            descriptor = os.dup(root)
            try:
                for part in path.relative_to(paths.frontend_state_dir).parts:
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                        os.fsync(descriptor)
                    except FileExistsError:
                        pass
                    following = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = following
                if path != paths.static_dir and os.fstat(descriptor).st_mode & 0o077:
                    raise StorageConfigurationError("Frontend-private directories must have mode 0700.")
            except OSError as error:
                raise StorageConfigurationError("Frontend-private storage contains an unsafe or unavailable directory.") from error
            finally:
                os.close(descriptor)
    return paths.frontend_state_dir


def check_storage(environ=None):
    """Validate existing deployment storage without importing or writing app state."""
    environment = os.environ if environ is None else environ
    if environment.get("QC_TOOL_DATA_ROOT"):
        if environment.get("QC_TOOL_PERSISTENT_STORAGE_ROOT") != environment["QC_TOOL_DATA_ROOT"]:
            raise StorageConfigurationError("The persistent browser root must match QC_TOOL_DATA_ROOT.")
        return check_layout(environment, require_identity=True)
    with _checked_storage(environment) as (root, _descriptor):
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
    environment = os.environ if environment is None else environment
    if environment.get("QC_TOOL_DATA_ROOT"):
        check_storage(environment)
        _root, roots = layout_roots(environment)
        for path, writable in roots.values():
            if writable:
                with _directory(path.parts[1:]) as descriptor:
                    _probe_at(path, descriptor)
        return
    with _checked_storage(environment) as (root, descriptor):
        _probe_at(root, descriptor)


def _probe_at(root, root_descriptor):
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
