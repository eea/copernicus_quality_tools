"""Private, durable operation journals; never store credentials in these files."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import UUID

from django.conf import settings

from qc_tool.common import CONFIG
from .errors import TransferBusy, TransferError


MAX_JOURNAL_BYTES = 32 * 1024 * 1024
OPERATION_STATUSES = {"staged", "planned", "queued", "running", "recovery_required", "completed", "cancelled", "failed"}
_execution_lease = ContextVar("qc_transfer_execution_lease", default=None)


def execution_lease_descriptor():
    """Let a native child retain admission if its Python runner disappears."""
    return _execution_lease.get()


def now():
    return datetime.now(timezone.utc).isoformat()


def _directory_path():
    return Path(getattr(settings, "QC_TOOL_TRANSFER_DIR", CONFIG["work_dir"] / "data-transfer"))


def directory():
    path = _directory_path()
    missing = []
    parent = path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    status = path.lstat()
    if not stat.S_ISDIR(status.st_mode) or status.st_mode & 0o077:
        raise TransferError("Data transfer storage must be a private real directory (0700).")
    for created in reversed(missing):
        sync_directory(created)
        sync_directory(created.parent)
    return path


def operation_dir(operation_id, *, create=False):
    try:
        if str(UUID(str(operation_id))) != str(operation_id):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise TransferError("Choose a valid transfer operation.") from error
    path = directory() / str(operation_id)
    if create:
        path.mkdir(mode=0o700)
        sync_directory(path.parent)
    try:
        status = path.lstat()
    except FileNotFoundError as error:
        raise TransferError("This transfer operation is unavailable.") from error
    if not stat.S_ISDIR(status.st_mode) or status.st_mode & 0o077:
        raise TransferError("Transfer operation storage is unsafe.")
    return path


def write_json(path, value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise TransferError("The transfer journal contains unsupported data.") from error
    # Never replace a readable journal with one the recovery reader refuses.
    # In particular, a large reviewed account mapping must fail before queuing
    # or pinning, while the last valid staged operation remains recoverable.
    if len(raw) > MAX_JOURNAL_BYTES:
        raise TransferError("The transfer review exceeds the private journal limit. Select fewer accounts or use the native backup procedure.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        sync_directory(path.parent)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def read_json(path, *, limit=MAX_JOURNAL_BYTES):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate journal key.")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("Non-finite journal number.")

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            status = os.fstat(handle.fileno())
            if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
                raise ValueError
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise TransferError("The transfer journal cannot be read safely. Operator recovery is required.") from error


def read_operation(operation_id):
    value = read_json(operation_dir(operation_id) / "operation.json")
    if (not isinstance(value, dict) or value.get("id") != str(operation_id)
            or type(value.get("version")) is not int or value["version"] != 1
            or not isinstance(value.get("kind"), str) or value["kind"] not in {"import", "export"}
            or not isinstance(value.get("status"), str) or value["status"] not in OPERATION_STATUSES
            or type(value.get("actor_id")) is not int or value["actor_id"] <= 0
            or not isinstance(value.get("actor_name"), str)
            or ("actor_database" in value and (
                not isinstance(value["actor_database"], str) or not value["actor_database"]
                or "\x00" in value["actor_database"]))
            or not isinstance(value.get("message"), str) or not isinstance(value.get("error"), str)
            or not isinstance(value.get("result"), dict)
            or (value.get("plan") is not None and not isinstance(value["plan"], dict))):
        raise TransferError("The transfer journal has an unsupported format.")
    try:
        for key in ("created_at", "updated_at"):
            timestamp = datetime.fromisoformat(value[key])
            if timestamp.utcoffset() is None:
                raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise TransferError("The transfer journal has an unsupported timestamp format.") from error
    from .plan_storage import validate_stored_plan
    validate_stored_plan(value.get("core_plan"))
    return value


def save_operation(operation):
    from .plan_storage import compact_operation
    operation["updated_at"] = now()
    write_json(operation_dir(operation["id"]) / "operation.json", compact_operation(operation))
    return operation


@contextmanager
def execution_lock():
    try:
        descriptor = os.open(directory() / "execution.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as error:
        raise TransferError("Transfer execution locking is unavailable.") from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
            raise TransferError("Transfer execution locking is unavailable.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise TransferBusy("Another transfer is running. Wait for it to finish before retrying.") from error
        except OSError as error:
            raise TransferError("Transfer execution locking is unavailable.") from error
        token = _execution_lease.set(descriptor)
        try:
            yield
        finally:
            _execution_lease.reset(token)
    finally:
        os.close(descriptor)


def execution_active():
    """Probe the existing execution lock without creating or changing files.

    This is only a presentation hint. Mutating actions must acquire the lock
    themselves because the runner can start or finish immediately after a probe.
    """
    try:
        path = _directory_path()
        status = path.lstat()
        if not stat.S_ISDIR(status.st_mode) or status.st_mode & 0o077:
            raise TransferError("Data transfer storage must be a private real directory (0700).")
        descriptor = os.open(path / "execution.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise TransferError("Transfer execution locking is unavailable.") from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
            raise TransferError("Transfer execution locking is unavailable.")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError as error:
            raise TransferError("Transfer execution locking is unavailable.") from error
        return False
    finally:
        os.close(descriptor)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
