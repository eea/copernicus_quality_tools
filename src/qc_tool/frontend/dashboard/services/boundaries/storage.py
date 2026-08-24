"""Durable publication and atomic selection of boundary generations."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import logging
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Iterator, Optional, Union
import uuid

from .contracts import LIVE_DIRECTORY_NAMES
from .errors import (
    BoundaryPackageBusy,
    BoundaryPackageConfigurationError,
    BoundaryPackageError,
    BoundaryPackagePromotionError,
)
from .layout import (
    CURRENT_POINTER_NAME,
    compatibility_link_target,
    current_pointer,
    current_pointer_target,
    generation_dir,
    generations_dir,
    path_lexists,
)


logger = logging.getLogger(__name__)

_LOCK_FILENAME = ".boundary-package.lock"
_GENERATION_DIRECTORY_MODE = 0o550
_GENERATION_FILE_MODE = 0o440


def prepare_boundary_root(boundary_dir: Union[str, os.PathLike]) -> Path:
    """Resolve a trusted root used by all boundary service processes."""

    root = Path(boundary_dir)
    if root.is_symlink():
        raise BoundaryPackageConfigurationError("boundary directory cannot be a symlink")
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o750)
        if root.is_symlink():
            raise BoundaryPackageConfigurationError("boundary directory cannot be a symlink")
        root = root.resolve(strict=True)
        root_stat = root.stat()
    except BoundaryPackageError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BoundaryPackageConfigurationError("boundary directory is unavailable") from exc

    if not root.is_dir():
        raise BoundaryPackageConfigurationError("boundary path is not a directory")
    if root_stat.st_mode & stat.S_IWOTH:
        raise BoundaryPackageConfigurationError("boundary directory is world-writable")
    trusted_group_ids = {os.getegid(), *os.getgroups()}
    if root_stat.st_mode & stat.S_IWGRP and root_stat.st_gid not in trusted_group_ids:
        raise BoundaryPackageConfigurationError("boundary directory has an untrusted group")
    if root_stat.st_uid not in (0, os.geteuid()):
        raise BoundaryPackageConfigurationError("boundary directory has an untrusted owner")
    return root


@contextmanager
def boundary_package_lock(root: Path, *, timeout: float) -> Iterator[None]:
    """Serialize all staging and activation work across cooperating processes."""

    lock_path = root / _LOCK_FILENAME
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise BoundaryPackageConfigurationError("promotion lock is not a regular file")
        os.fchmod(descriptor, 0o600)
    except BoundaryPackageError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BoundaryPackageConfigurationError("promotion lock cannot be opened") from exc

    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BoundaryPackageBusy("promotion lock timed out")
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def publish_generation(root: Path, payload_dir: Path, generation_id: str) -> Path:
    """Move one complete payload into the immutable generations namespace."""

    parent = _prepare_managed_directory(generations_dir(root), mode=0o750)
    destination = generation_dir(root, generation_id)
    if path_lexists(destination):
        raise BoundaryPackagePromotionError("boundary generation already exists")

    _validate_generation_tree(payload_dir)
    try:
        os.replace(payload_dir, destination)
        _freeze_generation_tree(destination)
        _fsync_directory(destination)
        _fsync_directory(parent)
    except OSError as exc:
        # Never delete a possibly complete generation automatically. It is not
        # active until the current pointer is replaced and can be audited later.
        raise BoundaryPackagePromotionError("generation publication failed") from exc
    return destination


def activate_generation(root: Path, generation_id: str) -> None:
    """Atomically replace the single pointer selecting the active package."""

    destination = generation_dir(root, generation_id)
    _validate_published_generation(destination)
    pointer = current_pointer(root)
    if path_lexists(pointer) and not pointer.is_symlink():
        raise BoundaryPackageConfigurationError("boundary current pointer is not a symlink")

    temporary_pointer = root / f".{CURRENT_POINTER_NAME}.tmp-{uuid.uuid4().hex}"
    try:
        os.symlink(current_pointer_target(generation_id), temporary_pointer)
        os.replace(temporary_pointer, pointer)
        _fsync_directory(root)
    except OSError as exc:
        raise BoundaryPackagePromotionError("active generation pointer update failed") from exc
    finally:
        try:
            temporary_pointer.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove a temporary boundary pointer")


def ensure_fresh_compatibility_links(root: Path) -> None:
    """Install legacy raster/vector paths when neither contains old data."""

    for name in LIVE_DIRECTORY_NAMES:
        target = root / name
        if path_lexists(target):
            if not is_compatibility_link(root, name):
                raise BoundaryPackageConfigurationError(
                    f"legacy {name} path requires explicit migration"
                )
            continue
        _install_compatibility_link(root, name)
    _fsync_directory(root)


def is_compatibility_link(root: Path, directory_name: str) -> bool:
    path = root / directory_name
    if not path.is_symlink():
        return False
    try:
        return os.readlink(path) == compatibility_link_target(directory_name)
    except OSError:
        return False


def _install_compatibility_link(root: Path, directory_name: str) -> None:
    target = root / directory_name
    temporary_link = root / f".boundary-link-{directory_name}-{uuid.uuid4().hex}"
    try:
        os.symlink(compatibility_link_target(directory_name), temporary_link)
        os.replace(temporary_link, target)
    except OSError as exc:
        raise BoundaryPackagePromotionError("compatibility link installation failed") from exc
    finally:
        try:
            temporary_link.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove a temporary compatibility link")


def _prepare_managed_directory(path: Path, *, mode: int) -> Path:
    if path.is_symlink():
        raise BoundaryPackageConfigurationError("managed storage directory is a symlink")
    try:
        path.mkdir(mode=mode, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise BoundaryPackageConfigurationError("managed storage path is not a directory")
        os.chmod(path, mode)
        return path
    except BoundaryPackageError:
        raise
    except OSError as exc:
        raise BoundaryPackageConfigurationError("managed storage directory is unavailable") from exc


def _validate_generation_tree(generation_path: Path) -> None:
    if generation_path.is_symlink() or not generation_path.is_dir():
        raise BoundaryPackageConfigurationError("generation payload is not a directory")
    with os.scandir(generation_path) as entries:
        actual_roots = {entry.name for entry in entries}
    if actual_roots != set(LIVE_DIRECTORY_NAMES):
        raise BoundaryPackageConfigurationError("generation payload roots are invalid")
    for name in LIVE_DIRECTORY_NAMES:
        _validate_regular_tree(generation_path / name)


def _validate_regular_tree(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise BoundaryPackageConfigurationError("generation contains an invalid directory")
    with os.scandir(path) as entries:
        for entry in entries:
            entry_path = Path(entry.path)
            if entry.is_symlink():
                raise BoundaryPackageConfigurationError("generation contains a link")
            if entry.is_dir(follow_symlinks=False):
                _validate_regular_tree(entry_path)
            elif not entry.is_file(follow_symlinks=False):
                raise BoundaryPackageConfigurationError("generation contains a special file")


def _freeze_generation_tree(generation_path: Path) -> None:
    for current_root, directory_names, file_names in os.walk(generation_path, topdown=False):
        current_path = Path(current_root)
        for filename in file_names:
            file_path = current_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                raise BoundaryPackageConfigurationError("generation file changed during publication")
            os.chmod(file_path, _GENERATION_FILE_MODE)
            _fsync_regular_file(file_path)
        for directory_name in directory_names:
            directory_path = current_path / directory_name
            if directory_path.is_symlink() or not directory_path.is_dir():
                raise BoundaryPackageConfigurationError(
                    "generation directory changed during publication"
                )
        os.chmod(current_path, _GENERATION_DIRECTORY_MODE)
        _fsync_directory(current_path)


def _validate_published_generation(generation_path: Path) -> None:
    _validate_generation_tree(generation_path)
    if stat.S_IMODE(generation_path.stat().st_mode) & 0o222:
        raise BoundaryPackageConfigurationError("published generation is mutable")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise
        logger.warning("Filesystem does not support directory fsync: %s", path.name)
    finally:
        os.close(descriptor)


def _fsync_regular_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove_tree(path: Path) -> None:
    """Best-effort cleanup for a service-created, explicitly scoped path."""

    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError:
        logger.exception("Could not remove private boundary-package staging data")
