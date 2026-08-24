"""Bounded, atomic storage for the operator-managed announcement message."""

import os
from pathlib import Path
from secrets import token_hex
import stat


MAX_ANNOUNCEMENT_BYTES = 64 * 1024


class AnnouncementStorageError(Exception):
    """Announcement state is invalid or cannot be accessed safely."""


def read_announcement(path):
    """Return the current UTF-8 message, or an empty string when absent."""

    target = _safe_target(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(target, flags)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise AnnouncementStorageError from exc
    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            raise AnnouncementStorageError
        with os.fdopen(descriptor, "rb") as announcement_file:
            descriptor = None
            payload = announcement_file.read(MAX_ANNOUNCEMENT_BYTES + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) > MAX_ANNOUNCEMENT_BYTES:
        raise AnnouncementStorageError
    try:
        return payload.decode("utf-8")
    except UnicodeError as exc:
        raise AnnouncementStorageError from exc


def write_announcement(path, message):
    """Atomically replace the message without following a target symlink."""

    if not isinstance(message, str):
        raise AnnouncementStorageError
    try:
        payload = message.encode("utf-8")
    except UnicodeError as exc:
        raise AnnouncementStorageError from exc
    if len(payload) > MAX_ANNOUNCEMENT_BYTES:
        raise AnnouncementStorageError

    target = _safe_target(path)
    if target.is_symlink():
        raise AnnouncementStorageError
    try:
        existing = target.stat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise AnnouncementStorageError from exc
    else:
        if not stat.S_ISREG(existing.st_mode):
            raise AnnouncementStorageError

    staged = target.with_name(".{}.{}.tmp".format(target.name, token_hex(12)))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(staged, flags, 0o600)
        with os.fdopen(descriptor, "wb") as staged_file:
            descriptor = None
            staged_file.write(payload)
            staged_file.flush()
            os.fsync(staged_file.fileno())
        os.replace(staged, target)
        _fsync_directory(target.parent)
    except OSError as exc:
        raise AnnouncementStorageError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            staged.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _safe_target(path):
    candidate = Path(path)
    if not candidate.name or candidate.name in {".", ".."}:
        raise AnnouncementStorageError
    if candidate.parent.is_symlink():
        raise AnnouncementStorageError
    try:
        parent = candidate.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AnnouncementStorageError from exc
    if not parent.is_dir():
        raise AnnouncementStorageError
    return parent / candidate.name


def _fsync_directory(directory):
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

