"""Reversible, same-filesystem moves coordinated with database maintenance.

Only unreferenced, individually reviewed files enter this private quarantine.
An intent is durable before a rename; interrupted moves stay discoverable.
Restore never replaces an existing name. No automatic purge is provided.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
import stat
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.utils.crypto import constant_time_compare

from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.dashboard.services.maintenance import MaintenanceError
from qc_tool.frontend.dashboard.services.maintenance.barrier import ready_barrier

from . import files
from .files import StorageError


_STATES = {"moving", "quarantined", "restoring", "restored", "recovery_required"}
_JOURNAL_LIMIT = 32 * 1024


def _now():
    return datetime.now(timezone.utc).isoformat()


def _authorize(actor):
    try:
        current = get_user_model().objects.get(pk=actor.pk, username=actor.get_username())
        if (not constant_time_compare(current.password, actor.password)
                or not access_for(current).is_administrator):
            raise ValueError
        return current
    except (AttributeError, ValueError, get_user_model().DoesNotExist) as error:
        raise StorageError("Sign in as an active administrator on the current database.", status_code=403) from error
    except DatabaseError as error:
        raise StorageError("Administrator access could not be verified. No files were changed.", status_code=503) from error


@contextmanager
def _guard(actor, generation):
    if type(generation) is not int or generation < 0:
        raise StorageError("Maintenance changed. Reload and review this action.")
    try:
        with store.execution_lock(), ready_barrier(generation=generation):
            yield _authorize(actor)
    except (MaintenanceError, TransferError) as error:
        raise StorageError(str(error)) from error
    except OSError as error:
        raise StorageError("The storage operation could not finish. Its files were retained; review Trash before retrying.",
                           status_code=503) from error


def _usage(area, path, *, assert_safe=False):
    from .references import StorageReferenceError, assert_unreferenced, describe_references
    try:
        if assert_safe:
            return assert_unreferenced(area, path, is_directory=False)
        return describe_references(area, path, is_directory=False)
    except StorageReferenceError as error:
        raise StorageError(str(error), code="referenced_storage",
                           status_code=getattr(error, "status_code", 409)) from error


def _review(area, path, fingerprint):
    return sha256(json.dumps([1, area, path, fingerprint], separators=(",", ":")).encode()).hexdigest()


def preview_quarantine(area, path, actor):
    _authorize(actor)
    entry = files.inspect_entry(area, path)
    reason = files.quarantine_reason(area, path, entry)
    usage = _usage(area, path)
    allowed = not reason and usage.get("checked", False) and usage.get("can_quarantine", False)
    return {"area": area, "path": path, "entry": entry, "usage": usage,
            "can_quarantine": allowed, "message": reason or usage.get("message", ""),
            "review_hash": _review(area, path, entry["fingerprint"])}


def _identity(status):
    return [status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns]


def _require_current_parent(area, path, parent):
    """A retained descriptor must still identify the configured destination."""
    parts = files._parts(area, path, allow_empty=False)
    with files.directory_descriptor(area, parts[:-1]) as current:
        held, present = os.fstat(parent), os.fstat(current)
        if (held.st_dev, held.st_ino) != (present.st_dev, present.st_ino):
            raise StorageError("This folder changed. Reload and review the file before continuing.")


def _private_directory(parent, name, *, create=False):
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    descriptor = os.open(name, files._DIRECTORY_FLAGS, dir_fd=parent)
    status = os.fstat(descriptor)
    if status.st_mode & 0o077 or status.st_uid != os.geteuid():
        os.close(descriptor)
        raise StorageError("Trash storage must be a private, application-owned real directory.")
    return descriptor


@contextmanager
def _trash_directory(area, *, create=False):
    if area == "published":
        raise StorageError("Published submissions cannot be moved to trash.")
    with files.root_descriptor(area) as root:
        descriptor = None
        try:
            try:
                descriptor = _private_directory(root, files.TRASH_DIRECTORY, create=create)
            except FileNotFoundError:
                if create:
                    raise
            if descriptor is not None and os.fstat(root).st_dev != os.fstat(descriptor).st_dev:
                raise StorageError("Trash must share its storage area's filesystem.")
            yield root, descriptor
        finally:
            if descriptor is not None:
                os.close(descriptor)


def _valid_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        return value
    except (ValueError, TypeError, AttributeError) as error:
        raise StorageError("Choose a valid trash operation.", status_code=404) from error


def _write(directory, journal):
    journal["updated_at"] = _now()
    payload = json.dumps(journal, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    if len(payload) > _JOURNAL_LIMIT:
        raise StorageError("The trash journal exceeds its supported size.")
    name = ".journal-" + uuid4().hex
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=directory)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(name, "journal.json", src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def _read(directory, area, operation_id):
    descriptor = os.open("journal.json", files._FILE_FLAGS, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_mode & 0o077:
            raise StorageError("The trash journal is unsafe. Keep its files for recovery.")
        raw = handle.read(_JOURNAL_LIMIT + 1)
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
        if (len(raw) > _JOURNAL_LIMIT or type(value["version"]) is not int or value["version"] != 1 or value["id"] != operation_id
                or value["area"] != area or value["state"] not in _STATES
                or type(value["root_identity"]) is not list or len(value["root_identity"]) != 2
                or any(type(item) is not int for item in value["root_identity"])
                or not isinstance(value["source_identity"], list) or len(value["source_identity"]) != 4
                or any(type(item) is not int for item in value["source_identity"])):
            raise ValueError
        files._parts(area, value["path"], allow_empty=False)
        if files.quarantine_reason(area, value["path"], {"kind": "file"}):
            raise ValueError
        for name in ("created_at", "updated_at"):
            if datetime.fromisoformat(value[name]).utcoffset() is None:
                raise ValueError
        if (not isinstance(value["actor_name"], str) or not isinstance(value["message"], str)
                or not isinstance(value.get("restored_by", ""), str)):
            raise ValueError
        if value.get("payload_identity") is not None and (
            not isinstance(value["payload_identity"], list) or len(value["payload_identity"]) != 4
            or any(type(item) is not int for item in value["payload_identity"])
        ):
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as error:
        raise StorageError("The trash journal cannot be read safely. Keep its files for recovery.") from error


def _public(journal):
    return {"id": journal["id"], "area": journal["area"], "path": journal["path"],
            "name": journal["path"].rsplit("/", 1)[-1], "state": journal["state"],
            "size_bytes": (journal.get("payload_identity") or journal["source_identity"])[2],
            "created_at": journal["created_at"], "updated_at": journal["updated_at"],
            "actor_name": journal["actor_name"], "restored_by": journal.get("restored_by", ""),
            "message": journal["message"], "can_restore": journal["state"] != "restored"}


def quarantine(area, path, actor, generation, review_hash):
    with _guard(actor, generation) as current:
        entry = files.inspect_entry(area, path)
        reason = files.quarantine_reason(area, path, entry)
        if reason:
            raise StorageError(reason)
        if not isinstance(review_hash, str) or not constant_time_compare(
            review_hash, _review(area, path, entry["fingerprint"])
        ):
            raise StorageError("This file changed. Review it again before moving it to trash.")
        _usage(area, path, assert_safe=True)
        parts = files._parts(area, path, allow_empty=False)
        with files.directory_descriptor(area, parts[:-1]) as parent, files._open_file_at(area, path, parent, parts[-1]) as source:
            fcntl.flock(source.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            status = os.fstat(source.fileno())
            if files.entry_fingerprint(status) != entry["fingerprint"]:
                raise StorageError("This file changed. Review it again before moving it to trash.")
            _require_current_parent(area, path, parent)
            with _trash_directory(area, create=True) as (root, trash):
                operation_id = str(uuid4())
                os.mkdir(operation_id, mode=0o700, dir_fd=trash)
                os.fsync(trash)
                operation = _private_directory(trash, operation_id)
                try:
                    journal = {"version": 1, "id": operation_id, "area": area, "path": path,
                        "state": "moving", "root_identity": [os.fstat(root).st_dev, os.fstat(root).st_ino],
                        "source_identity": _identity(status), "payload_identity": None,
                        "created_at": _now(), "actor_id": current.pk, "actor_name": current.get_username(),
                        "message": "Move intent recorded. The file is retained until explicitly restored."}
                    _write(operation, journal)
                    # This private, newly created directory has no competing
                    # payload. Existing user names are never overwritten.
                    os.rename(parts[-1], "payload", src_dir_fd=parent, dst_dir_fd=operation)
                    os.fsync(parent)
                    os.fsync(operation)
                    moved = os.stat("payload", dir_fd=operation, follow_symlinks=False)
                    journal["payload_identity"] = _identity(moved)
                    if not stat.S_ISREG(moved.st_mode) or moved.st_nlink != 1 or _identity(moved) != _identity(status):
                        journal.update(state="recovery_required", message="The file changed during the move. Its bytes were retained; review and restore it before continuing.")
                        _write(operation, journal)
                        raise StorageError(journal["message"])
                    journal.update(state="quarantined", message="Moved to trash. No permanent deletion was performed.")
                    _write(operation, journal)
                    return _public(journal)
                finally:
                    os.close(operation)


def list_trash(area, *, page=1, page_size=50):
    files._configuration(area)
    if area == "published":
        return {"area": area, "entries": [], "page": 1, "total": 0,
                "has_previous": False, "has_next": False, "scan_limited": False}
    entries, limited = [], False
    with _trash_directory(area) as (_root, trash):
        if trash is not None:
            with os.scandir(trash) as iterator:
                for index, item in enumerate(iterator):
                    if index >= files.MAX_SCAN_ENTRIES:
                        limited = True
                        break
                    descriptor = None
                    try:
                        _valid_id(item.name)
                        descriptor = _private_directory(trash, item.name)
                        entries.append(_public(_read(descriptor, area, item.name)))
                    except (StorageError, OSError):
                        # An unreadable journal is visible, never silently
                        # discarded or guessed to contain a safe restore path.
                        entries.append({"id": item.name, "area": area, "name": "Unreadable trash operation",
                            "state": "recovery_required", "message": "Its private journal is unavailable. Keep its files for operator recovery.",
                            "can_restore": False})
                    finally:
                        if descriptor is not None:
                            os.close(descriptor)
    entries.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    page_size = min(max(page_size if type(page_size) is int else 50, 1), 100)
    try:
        page = max(int(page), 1)
    except (ValueError, TypeError):
        page = 1
    total = len(entries)
    page = min(page, max((total + page_size - 1) // page_size, 1))
    return {"area": area, "entries": entries[(page - 1) * page_size:page * page_size], "page": page,
            "total": total, "has_previous": page > 1, "has_next": page * page_size < total, "scan_limited": limited}


@contextmanager
def _verified_restore_source(area, path, directory, name, expected, *, links=(1,)):
    """Hash and publish the same no-follow descriptor, never request evidence."""
    from .references import StorageReferenceError, assert_restore_safe

    descriptor = os.open(name, files._FILE_FLAGS, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink not in links or _identity(before) != expected:
            raise StorageError("The retained file changed. Keep it for operator recovery.")
        checksum, size = sha256(), 0
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
            size += len(chunk)
        if size != before.st_size or files.entry_fingerprint(os.fstat(handle.fileno())) != files.entry_fingerprint(before):
            raise StorageError("The retained file changed during verification. No file was restored.")
        try:
            assert_restore_safe(area, path, evidence={"sha256": checksum.hexdigest(), "size": size})
        except StorageReferenceError as error:
            raise StorageError(str(error), code="restore_usage") from error
        yield handle


def _restore_payload(area, operation, parent, name, journal, payload):
    expected = journal.get("payload_identity") or journal["source_identity"]
    if not stat.S_ISREG(payload.st_mode) or _identity(payload) != expected:
        raise StorageError("The quarantined file changed. Keep it for operator recovery.")
    try:
        existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and not (
        journal["state"] == "restoring" and _identity(existing) == expected and payload.st_nlink == 2
    ):
        raise StorageError("A file already exists at the original path. It was not overwritten.")
    allowed_links = (2,) if existing is not None else (1,)
    with _verified_restore_source(area, journal["path"], operation, "payload", expected,
                                  links=allowed_links) as verified:
        _require_current_parent(area, journal["path"], parent)
        journal.update(state="restoring", message="Restore intent recorded; existing files will never be overwritten.")
        _write(operation, journal)
        if existing is None:
            try:
                os.link("payload", name, src_dir_fd=operation, dst_dir_fd=parent, follow_symlinks=False)
            except FileExistsError as error:
                raise StorageError("A file already exists at the original path. It was not overwritten.") from error
        os.fsync(parent)
        _require_current_parent(area, journal["path"], parent)
        restored = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(restored.st_mode) or _identity(restored) != expected
                or _identity(os.fstat(verified.fileno())) != expected):
            raise StorageError("The restored name changed unexpectedly. Keep its journal for recovery.")
        # Remove only our private duplicate after durable, exclusive publication;
        # this never unlinks a user-selected path.
        os.unlink("payload", dir_fd=operation)
        os.fsync(operation)


def restore(area, operation_id, actor, generation):
    operation_id = _valid_id(operation_id)
    with _guard(actor, generation) as current, _trash_directory(area) as (root, trash):
        if trash is None:
            raise StorageError("This trash operation is unavailable.", status_code=404)
        try:
            operation = _private_directory(trash, operation_id)
        except FileNotFoundError as error:
            raise StorageError("This trash operation is unavailable.", status_code=404) from error
        try:
            journal = _read(operation, area, operation_id)
            if journal["root_identity"] != [os.fstat(root).st_dev, os.fstat(root).st_ino]:
                raise StorageError("The configured storage area changed. Keep the quarantined file for recovery.")
            if journal["state"] == "restored":
                return _public(journal)
            parts = files._parts(area, journal["path"], allow_empty=False)
            with files.directory_descriptor(area, parts[:-1]) as parent:
                try:
                    payload = os.stat("payload", dir_fd=operation, follow_symlinks=False)
                except FileNotFoundError:
                    original = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    expected = journal.get("payload_identity") or journal["source_identity"]
                    if (not stat.S_ISREG(original.st_mode) or original.st_nlink != 1
                            or _identity(original) != expected):
                        raise StorageError("The interrupted move cannot be reconciled safely. Keep its journal for recovery.")
                    with _verified_restore_source(area, journal["path"], parent, parts[-1], expected):
                        _require_current_parent(area, journal["path"], parent)
                else:
                    _restore_payload(area, operation, parent, parts[-1], journal, payload)
                journal.update(state="restored", restored_by=current.get_username(),
                               message="Restored to its original path. Existing files were not overwritten.")
                _write(operation, journal)
                return _public(journal)
        finally:
            os.close(operation)
