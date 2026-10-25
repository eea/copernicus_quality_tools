"""Reversible retirement of demonstrably unused immutable boundary packages.

Historical jobs do not record their boundary generation in SQL. Consequently
any Job row protects every retained generation. Removal is a journaled move to
private trash, never an irreversible purge or an in-place package edit.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID, uuid4

from django.db import DatabaseError
from django.utils.crypto import constant_time_compare

from qc_tool.common import CONFIG
from qc_tool.database import selection
from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.transfers.storage_pins import describe_pins
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.models import Job
from .boundaries import BoundaryPackageError, resolve_boundary_generation
from .boundaries.layout import GENERATIONS_DIRECTORY_NAME, TRASH_DIRECTORY_NAME, validate_generation_id
from .boundaries.storage.locking import boundary_package_lock
from .storage_admin import files
from .storage_admin.control import authorize_storage_change, guarded_storage_change
from .storage_admin.files import StorageError
from .storage_admin.journals import private_directory, read_journal, rename_exclusive, write_journal


TRASH_DIRECTORY = TRASH_DIRECTORY_NAME
_MAX_TREE_ENTRIES = 100_000
_MAX_DEPTH = 32
_STATES = {"moving", "quarantined", "restoring", "restored", "recovery_required"}
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
JOB_RETENTION_MESSAGE = (
    "Boundary removal is unavailable while QC job history exists. Historical jobs do not record "
    "which boundary version they used, so every retained version remains protected."
)
DATABASE_RETENTION_MESSAGE = (
    "Boundary removal is unavailable because a retained restore database or database selection history may use these versions. "
    "Its boundary usage cannot be verified, so every retained version remains protected."
)


def _generation_id(value):
    try:
        return validate_generation_id(value)
    except (BoundaryPackageError, TypeError) as error:
        raise StorageError("Choose a valid retained boundary version.", status_code=400) from error


def _operation_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
        return value
    except (ValueError, AttributeError) as error:
        raise StorageError("Choose a valid boundary trash operation.", status_code=400) from error


def job_retention_reason():
    try:
        return JOB_RETENTION_MESSAGE if Job.objects.exists() else ""
    except DatabaseError as error:
        raise StorageError("QC job history could not be checked. Boundary removal remains unavailable.", status_code=503) from error


def removal_protection_reason():
    """Include switched-away databases and restores made without file plans.

    SQL on the active database cannot prove absence of historical usage in a
    retained copy. Deliberately retain all versions after any database switch
    or native restore attempt; corrupt or unknown journals are not absence.
    """
    reason = job_retention_reason()
    if reason:
        return reason
    try:
        if selection.read_state()["revision"]:
            return DATABASE_RETENTION_MESSAGE
        path = store._directory_path()
        try:
            descriptor = os.open(path, files._DIRECTORY_FLAGS)
        except FileNotFoundError:
            return ""
        try:
            status = os.fstat(descriptor)
            if status.st_mode & 0o077 or status.st_uid != os.geteuid():
                raise ValueError
            scanned_bytes = 0
            with os.scandir(descriptor) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= files.MAX_SCAN_ENTRIES:
                        raise ValueError
                    if entry.name in {"execution.lock", "database-selection.json"} and entry.is_file(follow_symlinks=False):
                        continue
                    operation_id = _operation_id(entry.name)
                    operation_dir = private_directory(descriptor, operation_id)
                    try:
                        metadata = os.stat("operation.json", dir_fd=operation_dir, follow_symlinks=False)
                        scanned_bytes += metadata.st_size
                        if scanned_bytes > 64 * 1024**2:
                            raise ValueError
                        operation = store.read_operation(operation_id)
                    finally:
                        os.close(operation_dir)
                    if operation.get("kind") == "import":
                        if operation.get("profile") == "database":
                            return DATABASE_RETENTION_MESSAGE
                        if not isinstance(operation.get("profile"), str) or operation["profile"] not in {"accounts", "application"}:
                            raise ValueError("unknown import profile")
        finally:
            os.close(descriptor)
        return ""
    except (TransferError, StorageError, OSError, ValueError, KeyError) as error:
        raise StorageError("Retained database history could not be checked safely. Boundary removal remains unavailable.", status_code=503) from error


@contextmanager
def _directory(parent, name):
    descriptor = os.open(name, files._DIRECTORY_FLAGS, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _identity(descriptor):
    status = os.fstat(descriptor)
    return [status.st_dev, status.st_ino]


def _tree(directory):
    """Fingerprint bounded, immutable, link-free content without reading bytes."""
    digest, count, size, scanned = sha256(), 0, 0, 0
    def visit(descriptor, prefix, depth):
        nonlocal count, size, scanned
        if depth > _MAX_DEPTH:
            raise StorageError("This boundary version exceeds the supported inspection depth.")
        metadata = os.fstat(descriptor)
        if metadata.st_mode & 0o222:
            raise StorageError("This boundary version is mutable. Keep it for operator review.")
        digest.update(json.dumps([prefix, metadata.st_dev, metadata.st_ino, metadata.st_size,
                                  metadata.st_mtime_ns, metadata.st_mode]).encode())
        entries = []
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                scanned += 1
                if scanned > _MAX_TREE_ENTRIES:
                    raise StorageError("This boundary version exceeds the supported inspection limit.")
                entries.append(entry.name)
        if not prefix and set(entries) != {"raster", "vector"}:
            raise StorageError("This boundary version has an unexpected package layout.")
        for name in sorted(entries):
            relative = prefix + "/" + name if prefix else name
            if (name in {".", ".."} or "/" in name or "\\" in name
                    or len(relative.encode("utf-8")) > 4096):
                raise StorageError("This boundary version contains an unsafe path.")
            status = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(status.st_mode):
                with _directory(descriptor, name) as child:
                    if _identity(child) != [status.st_dev, status.st_ino]:
                        raise StorageError("The boundary folder changed. Review it again.")
                    visit(child, relative, depth + 1)
            elif stat.S_ISREG(status.st_mode) and status.st_nlink == 1 and not status.st_mode & 0o222:
                digest.update(json.dumps([relative, status.st_dev, status.st_ino, status.st_size,
                                          status.st_mtime_ns, status.st_ctime_ns, status.st_mode]).encode())
                count += 1
                size += status.st_size
            else:
                raise StorageError("This boundary version contains a link, mutable file or special entry. Keep it for operator review.")
    visit(directory, "", 0)
    return {"fingerprint": digest.hexdigest(), "file_count": count, "size_bytes": size}


def _current(root):
    """Fail closed on unknown selection or aliases rather than guess usage."""
    try:
        generation = resolve_boundary_generation(CONFIG["boundary_dir"])
        if generation.managed:
            for name in ("raster", "vector"):
                status = os.stat(name, dir_fd=root, follow_symlinks=False)
                if not stat.S_ISLNK(status.st_mode) or os.readlink(name, dir_fd=root) != ".boundary-current/" + name:
                    raise StorageError("Boundary compatibility links are inconsistent. Keep all versions for operator review.")
        return generation
    except BoundaryPackageError as error:
        raise StorageError("The active boundary version could not be verified. Keep all versions for operator review.") from error


def _require_current_directories(root, generations):
    with files.root_descriptor("boundaries") as current, _directory(current, GENERATIONS_DIRECTORY_NAME) as parent:
        if _identity(current) != _identity(root) or _identity(parent) != _identity(generations):
            raise StorageError("Boundary storage changed. Reload and review the operation.")


def _inspect(root, generations, generation_id):
    current = _current(root)
    if current.generation_id == generation_id:
        raise StorageError("The active boundary package cannot be removed. Upload a replacement first.")
    reason = removal_protection_reason()
    if reason:
        raise StorageError(reason)
    path = GENERATIONS_DIRECTORY_NAME + "/" + generation_id
    try:
        if describe_pins("boundaries", path, is_directory=True):
            raise StorageError("A retained restore database protects this boundary version. Its files cannot be removed.")
    except TransferError as error:
        raise StorageError("Retained database file protection could not be checked. Boundary removal remains unavailable.") from error
    with _directory(generations, generation_id) as source:
        content = _tree(source)
        identity = _identity(source)
    review = sha256(json.dumps([1, generation_id, _identity(root), identity,
                               content["fingerprint"], current.generation_id]).encode()).hexdigest()
    return {**content, "generation_id": generation_id, "source_identity": identity, "review_hash": review}


def preview_removal(generation_id, actor):
    authorize_storage_change(actor, permission=AccountPermission.MANAGE_CONFIGURATION)
    generation_id = _generation_id(generation_id)
    try:
        with files.root_descriptor("boundaries") as root, _directory(root, GENERATIONS_DIRECTORY_NAME) as generations:
            return _inspect(root, generations, generation_id)
    except OSError as error:
        raise StorageError("This boundary version is unavailable or unsafe. No files were changed.") from error


@contextmanager
def _guard(actor, maintenance_generation):
    with guarded_storage_change(actor, maintenance_generation, permission=AccountPermission.MANAGE_CONFIGURATION) as current:
        try:
            root_path = Path(CONFIG["boundary_dir"])
            if root_path.is_symlink():
                raise StorageError("Boundary storage must be a real directory.")
            # Every publisher takes this same lock. Admission and the transfer
            # lock prevent new jobs, database switches and new retained pins.
            with boundary_package_lock(root_path, timeout=0), files.root_descriptor("boundaries") as root:
                with _directory(root, GENERATIONS_DIRECTORY_NAME) as generations:
                    yield current, root, generations
        except BoundaryPackageError as error:
            raise StorageError(error.user_message) from error


@contextmanager
def _trash(root, *, create=False):
    descriptor = None
    try:
        try:
            descriptor = private_directory(root, TRASH_DIRECTORY, create=create)
        except FileNotFoundError:
            if create:
                raise
        if descriptor is not None and os.fstat(root).st_dev != os.fstat(descriptor).st_dev:
            raise StorageError("Boundary trash must share the boundary storage filesystem.")
        yield descriptor
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read(operation, operation_id):
    journal = read_journal(operation)
    try:
        if (type(journal["version"]) is not int or journal["version"] != 1 or journal["id"] != operation_id
                or journal["state"] not in _STATES or _generation_id(journal["generation_id"]) != journal["generation_id"]
                or not isinstance(journal["fingerprint"], str) or not _FINGERPRINT.fullmatch(journal["fingerprint"])):
            raise ValueError
        for key in ("root_identity", "source_identity"):
            if type(journal[key]) is not list or len(journal[key]) != 2 or any(type(item) is not int for item in journal[key]):
                raise ValueError
        for key in ("file_count", "size_bytes"):
            if type(journal[key]) is not int or journal[key] < 0:
                raise ValueError
        for key in ("created_at", "updated_at"):
            if datetime.fromisoformat(journal[key]).utcoffset() is None:
                raise ValueError
        for key in ("actor_name", "message"):
            if not isinstance(journal[key], str):
                raise ValueError
    except (ValueError, TypeError, KeyError) as error:
        raise StorageError("The boundary trash journal is invalid. Keep its files for operator recovery.") from error
    return journal


def _public(journal):
    return {key: journal[key] for key in ("id", "generation_id", "state", "file_count", "size_bytes", "created_at", "actor_name", "message")}


def remove_generation(generation_id, actor, maintenance_generation, review_hash):
    generation_id = _generation_id(generation_id)
    with _guard(actor, maintenance_generation) as (current, root, generations):
        preview = _inspect(root, generations, generation_id)
        if not isinstance(review_hash, str) or not constant_time_compare(review_hash, preview["review_hash"]):
            raise StorageError("The boundary package changed. Review its removal again.")
        with _trash(root, create=True) as trash:
            operation_id = str(uuid4())
            os.mkdir(operation_id, mode=0o700, dir_fd=trash)
            os.fsync(trash)
            operation = private_directory(trash, operation_id)
            try:
                journal = {"version": 1, "id": operation_id, "generation_id": generation_id,
                           "state": "moving", "root_identity": _identity(root),
                           **{key: preview[key] for key in ("source_identity", "fingerprint", "file_count", "size_bytes")},
                           "created_at": datetime.now(timezone.utc).isoformat(), "actor_name": current.get_username(),
                           "message": "Removal intent recorded. The complete boundary package is retained for recovery."}
                write_journal(operation, journal)
                _require_current_directories(root, generations)
                rename_exclusive(generations, generation_id, operation, "payload")
                os.fsync(generations)
                os.fsync(operation)
                with _directory(operation, "payload") as payload:
                    if _identity(payload) != preview["source_identity"] or _tree(payload)["fingerprint"] != preview["fingerprint"]:
                        journal.update(state="recovery_required", message="The package changed during removal. Its files were retained for operator recovery.")
                        write_journal(operation, journal)
                        raise StorageError(journal["message"])
                journal.update(state="quarantined", message="Moved to boundary trash. Restore it here if needed; no files were permanently deleted.")
                write_journal(operation, journal)
                return _public(journal)
            finally:
                os.close(operation)


def list_trash(*, page=1, page_size=25):
    """Read bounded private journals; an unreadable entry never grants actions."""
    entries, warnings = [], []
    try:
        with files.root_descriptor("boundaries") as root, _trash(root) as trash:
            if trash is not None:
                with os.scandir(trash) as iterator:
                    for index, entry in enumerate(iterator):
                        if index >= files.MAX_SCAN_ENTRIES:
                            warnings.append("Boundary trash reached its inspection limit. Additional entries were retained.")
                            break
                        try:
                            operation_id = _operation_id(entry.name)
                            operation = private_directory(trash, operation_id)
                            try:
                                row = _public(_read(operation, operation_id))
                                row["can_restore"] = row["state"] != "restored"
                                entries.append(row)
                            finally:
                                os.close(operation)
                        except (StorageError, OSError):
                            warnings.append("A boundary trash journal is unavailable. Keep its files for operator recovery.")
    except (StorageError, OSError):
        warnings.append("Boundary trash is unavailable. No files were changed.")
    entries.sort(key=lambda item: item["created_at"], reverse=True)
    try:
        page = max(int(page), 1)
    except (ValueError, TypeError):
        page = 1
    page_size = min(max(page_size, 1), 100)
    total = len(entries)
    page = min(page, max((total + page_size - 1) // page_size, 1))
    return {"entries": entries[(page - 1) * page_size:page * page_size], "total": total,
            "warnings": list(dict.fromkeys(warnings)), "page": page,
            "has_previous": page > 1, "has_next": page * page_size < total}


def restore_generation(operation_id, actor, maintenance_generation):
    operation_id = _operation_id(operation_id)
    with _guard(actor, maintenance_generation) as (current, root, generations), _trash(root) as trash:
        if trash is None:
            raise StorageError("This boundary trash operation is unavailable.", status_code=404)
        operation = private_directory(trash, operation_id)
        try:
            journal = _read(operation, operation_id)
            if journal["root_identity"] != _identity(root):
                raise StorageError("Boundary storage changed. Keep the retained package for operator recovery.")
            if journal["state"] == "restored":
                return _public(journal)
            generation_id = journal["generation_id"]
            try:
                payload = os.open("payload", files._DIRECTORY_FLAGS, dir_fd=operation)
            except FileNotFoundError:
                # Lost acknowledgement after the exclusive rename, or a move
                # intent that never moved. Verify the original exact directory.
                payload = os.open(generation_id, files._DIRECTORY_FLAGS, dir_fd=generations)
                moved = True
            else:
                moved = False
            try:
                if _identity(payload) != journal["source_identity"] or _tree(payload)["fingerprint"] != journal["fingerprint"]:
                    raise StorageError("The retained boundary package changed. Keep it for operator recovery.")
                _require_current_directories(root, generations)
                if not moved:
                    journal.update(state="restoring", restored_by=current.get_username(),
                                   message="Restore intent recorded. Existing version names will never be overwritten.")
                    write_journal(operation, journal)
                    try:
                        rename_exclusive(operation, "payload", generations, generation_id)
                    except FileExistsError as error:
                        raise StorageError("This boundary version name already exists. It was not overwritten.") from error
                    os.fsync(generations)
                    os.fsync(operation)
                with _directory(generations, generation_id) as restored:
                    if _identity(restored) != journal["source_identity"] or _tree(restored)["fingerprint"] != journal["fingerprint"]:
                        raise StorageError("The restored package changed unexpectedly. Keep its journal for operator recovery.")
                journal.update(state="restored", restored_by=current.get_username(),
                               message="The exact boundary version was restored. The active package selection was not changed.")
                write_journal(operation, journal)
                return _public(journal)
            finally:
                os.close(payload)
        finally:
            os.close(operation)
