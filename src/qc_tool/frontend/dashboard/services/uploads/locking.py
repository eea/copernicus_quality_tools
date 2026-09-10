"""Serialize registration by owner storage directory and delivery filename."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import os
import stat

from ._resumable.descriptor import validate_delivery_filename
from ._resumable.locks import upload_lock
from ._resumable.paths import _ensure_confined_directory
from ._resumable.errors import ResumableUploadError
from ._resumable.filesystem import read_flags, write_once_flags


@contextmanager
def delivery_filename_lock(user_root, filename):
    """Share one filesystem lock across browser and API upload identities."""

    validate_delivery_filename(filename)
    user_root = Path(user_root)
    uploads_root = user_root / "uploads"
    _ensure_confined_directory(uploads_root, parent=user_root, mode=0o700)
    lock_root = uploads_root / ("filename-" + sha256(filename.encode("utf-8")).hexdigest())
    _ensure_confined_directory(lock_root, parent=uploads_root, mode=0o700)
    with upload_lock(lock_root) as directory:
        yield directory


def require_available_filename(directory, *, storage_key=None):
    try:
        fd = os.open(".overwrite-intent", read_flags() | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ResumableUploadError("unsafe_upload_storage", "The upload recovery record is not safe.", 500)
        pending = source.read(65)
    if storage_key is None or pending != storage_key.encode("ascii"):
        raise ResumableUploadError("overwrite_pending", "An overwrite of this filename needs to finish. Retry that upload before adding another file with this name.", 409)


def mark_overwrite_intent(directory, storage_key):
    require_available_filename(directory, storage_key=storage_key)
    try:
        fd = os.open(".overwrite-intent", write_once_flags(), 0o600, dir_fd=directory)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as target:
        target.write(storage_key.encode("ascii"))
        target.flush()
        os.fsync(target.fileno())
    os.fsync(directory)


def clear_overwrite_intent(directory):
    try:
        os.unlink(".overwrite-intent", dir_fd=directory)
    except FileNotFoundError:
        return
    os.fsync(directory)
