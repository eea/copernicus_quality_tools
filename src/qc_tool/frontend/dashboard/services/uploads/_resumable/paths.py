"""Confined path construction for resumable delivery uploads."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat

from .descriptor import ResumableUploadDescriptor
from .errors import ResumableUploadError
from .filesystem import directory_flags, open_directory


@dataclass(frozen=True, slots=True)
class ResumableUploadPaths:
    user_root: Path
    chunks_dir: Path
    chunk_path: Path
    target_path: Path


def prepare_resumable_paths(
    descriptor: ResumableUploadDescriptor,
    *,
    media_root: str | os.PathLike[str],
    username: str,
    create: bool = True,
) -> ResumableUploadPaths:
    """Resolve confined staging paths, optionally creating private directories."""

    _validate_owner(username)
    try:
        root = Path(media_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResumableUploadError(
            "upload_storage_unavailable",
            "Upload storage is unavailable.",
            503,
        ) from exc

    user_root = root / username
    uploads_root = user_root / "uploads"
    chunks_dir = uploads_root / descriptor.storage_key

    if create:
        _ensure_confined_directory(user_root, parent=root, mode=0o750)
        _ensure_confined_directory(uploads_root, parent=user_root, mode=0o700)
        _ensure_confined_directory(chunks_dir, parent=uploads_root, mode=0o700)
    else:
        user_exists = _validate_optional_directory(user_root, parent=root)
        uploads_exist = user_exists and _validate_optional_directory(
            uploads_root,
            parent=user_root,
        )
        if uploads_exist:
            _validate_optional_directory(chunks_dir, parent=uploads_root)

    return ResumableUploadPaths(
        user_root=user_root,
        chunks_dir=chunks_dir,
        chunk_path=chunks_dir / f"chunk-{descriptor.chunk_number:08d}.part",
        target_path=user_root / descriptor.filename,
    )


def expected_chunk_paths(
    descriptor: ResumableUploadDescriptor,
    paths: ResumableUploadPaths,
) -> tuple[Path, ...]:
    return tuple(
        paths.chunks_dir / f"chunk-{number:08d}.part"
        for number in range(1, descriptor.total_chunks + 1)
    )


def _validate_owner(username) -> None:
    if not isinstance(username, str) or not username or "\x00" in username:
        raise _invalid_owner()
    try:
        encoded_length = len(username.encode("utf-8"))
    except UnicodeError as exc:
        raise _invalid_owner() from exc
    path = Path(username)
    if (
        path.name != username
        or "\\" in username
        or username in {".", ".."}
        or any(ord(character) < 32 for character in username)
        or encoded_length > 255
    ):
        raise _invalid_owner()


def _invalid_owner() -> ResumableUploadError:
    return ResumableUploadError(
        "invalid_upload_owner",
        "The upload owner is invalid.",
        403,
    )


def _ensure_confined_directory(path: Path, *, parent: Path, mode: int) -> None:
    _validate_child_path(path, parent)
    parent_descriptor = open_directory(parent)
    try:
        try:
            os.mkdir(path.name, mode=mode, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        try:
            directory_descriptor = os.open(
                path.name,
                directory_flags(),
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            raise _unsafe_storage() from exc
        try:
            if not stat.S_ISDIR(os.fstat(directory_descriptor).st_mode):
                raise _unsafe_storage()
            os.fchmod(directory_descriptor, mode)
        finally:
            os.close(directory_descriptor)
    except ResumableUploadError:
        raise
    except OSError as exc:
        raise ResumableUploadError(
            "upload_storage_unavailable",
            "Upload storage is unavailable.",
            503,
        ) from exc
    finally:
        os.close(parent_descriptor)


def _validate_optional_directory(path: Path, *, parent: Path) -> bool:
    _validate_child_path(path, parent)
    parent_descriptor = open_directory(parent)
    try:
        try:
            directory_descriptor = os.open(
                path.name,
                directory_flags(),
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _unsafe_storage() from exc
        try:
            if not stat.S_ISDIR(os.fstat(directory_descriptor).st_mode):
                raise _unsafe_storage()
            return True
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(parent_descriptor)


def _validate_child_path(path: Path, parent: Path) -> None:
    if path.parent != parent or path.name in {"", ".", ".."}:
        raise _unsafe_storage()


def _unsafe_storage() -> ResumableUploadError:
    return ResumableUploadError(
        "unsafe_upload_storage",
        "Upload storage is not safe.",
        500,
    )
