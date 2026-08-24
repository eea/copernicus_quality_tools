"""One-time, fail-closed migration of legacy raster/vector directories."""

from __future__ import annotations

import ctypes
import errno
import logging
import os
from pathlib import Path
import shutil
import sys

from .contracts import LIVE_DIRECTORY_NAMES
from .errors import BoundaryPackageConfigurationError, BoundaryPackageError
from .layout import (
    compatibility_link_target,
    current_pointer,
    legacy_backups_dir,
    new_generation_id,
    path_lexists,
)
from .resolver import resolve_boundary_generation
from .storage import (
    _fsync_directory,
    _prepare_managed_directory,
    activate_generation,
    is_compatibility_link,
    publish_generation,
)


logger = logging.getLogger(__name__)

_AT_FDCWD = -100
_RENAME_EXCHANGE = 2
_RENAME_SWAP = 2


def ensure_compatibility_layout(root: Path, migration_staging_dir: Path) -> None:
    """Ensure legacy paths resolve through the one managed current pointer.

    Direct legacy directories are first copied into an immutable generation.
    The pointer selects that byte-equivalent snapshot before each direct path is
    atomically exchanged with its compatibility symlink. Original directories
    are retained under ``.boundary-legacy-backups``.
    """

    states = {name: _legacy_path_state(root, name) for name in LIVE_DIRECTORY_NAMES}
    pointer_exists = path_lexists(current_pointer(root))
    active = (
        resolve_boundary_generation(root, allow_legacy=False)
        if pointer_exists
        else None
    )

    if all(state in ("missing", "compatibility") for state in states.values()):
        from .storage import ensure_fresh_compatibility_links

        ensure_fresh_compatibility_links(root)
        return

    if any(state == "unsafe" for state in states.values()):
        raise BoundaryPackageConfigurationError("legacy boundary path is unsafe")

    if pointer_exists:
        assert active is not None
        if not active.generation_id.startswith("legacy-"):
            raise BoundaryPackageConfigurationError(
                "direct legacy paths conflict with an active managed generation"
            )
        legacy_generation_id = active.generation_id
    else:
        if any(state == "compatibility" for state in states.values()):
            raise BoundaryPackageConfigurationError(
                "dangling compatibility link has no current generation"
            )
        legacy_generation_id = _publish_legacy_snapshot(root, migration_staging_dir)

    backup_root = _prepare_legacy_backup(root, legacy_generation_id)
    if not pointer_exists:
        activate_generation(root, legacy_generation_id)

    for name in LIVE_DIRECTORY_NAMES:
        state = _legacy_path_state(root, name)
        if state == "compatibility":
            continue
        if state == "missing":
            _install_missing_compatibility_link(root, name)
            continue
        if state != "directory":
            raise BoundaryPackageConfigurationError("legacy migration state is invalid")
        _exchange_legacy_directory(root, backup_root, name)

    _fsync_directory(root)
    _fsync_directory(backup_root)


def _publish_legacy_snapshot(root: Path, staging_dir: Path) -> str:
    generation_id = new_generation_id(legacy=True)
    payload = staging_dir / generation_id
    payload.mkdir(mode=0o700)

    for name in LIVE_DIRECTORY_NAMES:
        source = root / name
        destination = payload / name
        if not path_lexists(source):
            destination.mkdir(mode=0o750)
            continue
        if source.is_symlink() or not source.is_dir():
            raise BoundaryPackageConfigurationError("legacy boundary root is unsafe")
        try:
            shutil.copytree(source, destination, symlinks=True)
        except OSError as exc:
            raise BoundaryPackageConfigurationError("legacy boundary copy failed") from exc

    publish_generation(root, payload, generation_id)
    return generation_id


def _prepare_legacy_backup(root: Path, generation_id: str) -> Path:
    backup_parent = _prepare_managed_directory(legacy_backups_dir(root), mode=0o700)
    backup_root = backup_parent / generation_id
    if backup_root.is_symlink():
        raise BoundaryPackageConfigurationError("legacy backup is a symlink")
    try:
        backup_root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(backup_root, 0o700)
    except OSError as exc:
        raise BoundaryPackageConfigurationError("legacy backup cannot be prepared") from exc
    return backup_root


def _exchange_legacy_directory(root: Path, backup_root: Path, name: str) -> None:
    live_path = root / name
    backup_path = backup_root / name
    if path_lexists(backup_path):
        raise BoundaryPackageConfigurationError("legacy backup target already exists")
    try:
        os.symlink(compatibility_link_target(name), backup_path)
        _atomic_exchange(live_path, backup_path)
    except BoundaryPackageError:
        raise
    except OSError as exc:
        try:
            if backup_path.is_symlink():
                backup_path.unlink()
        except OSError:
            logger.exception("Could not remove an unused legacy migration link")
        raise BoundaryPackageConfigurationError(
            "filesystem does not support atomic legacy migration"
        ) from exc

    if not is_compatibility_link(root, name):
        raise BoundaryPackageConfigurationError("legacy compatibility exchange failed")
    if backup_path.is_symlink() or not backup_path.is_dir():
        raise BoundaryPackageConfigurationError("legacy directory backup was not retained")


def _install_missing_compatibility_link(root: Path, name: str) -> None:
    live_path = root / name
    try:
        os.symlink(compatibility_link_target(name), live_path)
    except OSError as exc:
        raise BoundaryPackageConfigurationError("compatibility link cannot be installed") from exc


def _legacy_path_state(root: Path, name: str) -> str:
    path = root / name
    if not path_lexists(path):
        return "missing"
    if is_compatibility_link(root, name):
        return "compatibility"
    if path.is_symlink():
        return "unsafe"
    if path.is_dir():
        return "directory"
    return "unsafe"


def _atomic_exchange(left: Path, right: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    left_bytes = os.fsencode(left)
    right_bytes = os.fsencode(right)

    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        result = rename(
            _AT_FDCWD,
            left_bytes,
            _AT_FDCWD,
            right_bytes,
            _RENAME_EXCHANGE,
        )
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(left_bytes, right_bytes, _RENAME_SWAP)
    else:
        raise OSError(errno.ENOTSUP, "atomic path exchange is unavailable")

    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
