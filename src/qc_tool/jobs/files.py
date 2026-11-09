"""No-follow reads and adjacent atomic writes for owned run artifacts."""

import os
import stat
from uuid import uuid4

from .errors import JobStorageError


def read_regular_bytes(path, *, limit):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise JobStorageError("Job artifact is not a regular file.")
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise JobStorageError("Job artifact exceeds its reader limit.")
        return raw
    except FileNotFoundError:
        raise
    except OSError as error:
        raise JobStorageError("Job artifact cannot be read safely.") from error


def publish_job_bytes(path, payload, *, replace=False):
    """Publish complete bytes; immutable snapshots permit identical retries only."""
    if path.is_symlink():
        raise JobStorageError("Job artifact target is a symbolic link.")
    temporary = path.parent / (".artifact-" + uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                if read_regular_bytes(path, limit=len(payload)) != payload:
                    raise JobStorageError("The retained job artifact has changed.")
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)
