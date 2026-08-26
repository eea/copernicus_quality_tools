"""Validation and preparation of the trusted boundary storage root."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Union

from ..errors import BoundaryPackageConfigurationError, BoundaryPackageError


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
