"""Validation and permission freezing for managed generation trees."""

import os
from pathlib import Path
import stat

from ..contracts import LIVE_DIRECTORY_NAMES
from ..errors import BoundaryPackageConfigurationError, BoundaryPackageError
from .constants import GENERATION_DIRECTORY_MODE, GENERATION_FILE_MODE
from .durability import fsync_directory, fsync_regular_file


def prepare_managed_directory(path: Path, *, mode: int) -> Path:
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
        raise BoundaryPackageConfigurationError(
            "managed storage directory is unavailable"
        ) from exc


def validate_generation_tree(generation_path: Path) -> None:
    if generation_path.is_symlink() or not generation_path.is_dir():
        raise BoundaryPackageConfigurationError("generation payload is not a directory")
    with os.scandir(generation_path) as entries:
        actual_roots = {entry.name for entry in entries}
    if actual_roots != set(LIVE_DIRECTORY_NAMES):
        raise BoundaryPackageConfigurationError("generation payload roots are invalid")
    for name in LIVE_DIRECTORY_NAMES:
        _validate_regular_tree(generation_path / name)


def freeze_generation_tree(generation_path: Path) -> None:
    for current_root, directory_names, file_names in os.walk(
        generation_path, topdown=False
    ):
        current_path = Path(current_root)
        for filename in file_names:
            file_path = current_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                raise BoundaryPackageConfigurationError(
                    "generation file changed during publication"
                )
            os.chmod(file_path, GENERATION_FILE_MODE)
            fsync_regular_file(file_path)
        for directory_name in directory_names:
            directory_path = current_path / directory_name
            if directory_path.is_symlink() or not directory_path.is_dir():
                raise BoundaryPackageConfigurationError(
                    "generation directory changed during publication"
                )
        os.chmod(current_path, GENERATION_DIRECTORY_MODE)
        fsync_directory(current_path)


def validate_published_generation(generation_path: Path) -> None:
    validate_generation_tree(generation_path)
    if stat.S_IMODE(generation_path.stat().st_mode) & 0o222:
        raise BoundaryPackageConfigurationError("published generation is mutable")


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
