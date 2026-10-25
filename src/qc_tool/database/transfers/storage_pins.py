"""Retained restore databases protect their shared files without SQL queries.

An inactive, unavailable or older database can still own these bytes. Pins are
private deployment journals, written before publication and deliberately never
released automatically. A future explicit database-retirement workflow must
review their retention; deleting an operation journal is not a cleanup policy.
"""

import os
from pathlib import Path
import re
import stat
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.urls import reverse

from qc_tool.common import CONFIG

from . import store
from .archive import validate_key
from .errors import TransferError


VERSION = 1
FILENAME = "storage-pin.json"
MAX_SCAN_OPERATIONS = 10_000
MAX_PIN_FILES = 100_000
MAX_SCANNED_FILES = 1_000_000
MAX_SCAN_BYTES = 64 * 1024**2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


def _operation_id(value):
    if not isinstance(value, str):
        raise TransferError("Retained restore storage has an invalid operation identity.")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as error:
        raise TransferError("Retained restore storage has an invalid operation identity.") from error
    return value


def _absolute_root(value):
    if not isinstance(value, (str, Path)):
        raise TransferError("Retained restore storage has an invalid root mapping.")
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or str(path) != str(value)
            or len(str(path)) > 4096 or "\\" in str(path)
            or any(ord(character) < 32 or ord(character) == 127 for character in str(path))):
        raise TransferError("Retained restore storage has an invalid root mapping.")
    return str(path)


def _private_directory(path):
    status = path.lstat()
    if not stat.S_ISDIR(status.st_mode) or status.st_mode & 0o077:
        raise TransferError("Retained restore storage must remain in private real directories.")


def _validate(document, operation_id):
    if (not isinstance(document, dict)
            or set(document) != {"version", "operation_id", "destination_database", "roots", "files"}
            or type(document["version"]) is not int or document["version"] != VERSION
            or _operation_id(document["operation_id"]) != operation_id):
        raise TransferError("The retained restore storage pin is invalid.")
    database = document["destination_database"]
    try:
        encoded_database = database.encode("utf-8") if isinstance(database, str) else b""
    except UnicodeError as error:
        raise TransferError("The retained restore database identity is invalid.") from error
    if (not isinstance(database, str) or not database or len(encoded_database) > 63
            or any(ord(character) < 32 or ord(character) == 127 for character in database)):
        raise TransferError("The retained restore database identity is invalid.")
    roots, entries = document["roots"], document["files"]
    if (not isinstance(roots, dict) or len(roots) > 1000
            or any(not isinstance(name, str) or not _ROOT.fullmatch(name) for name in roots)
            or not isinstance(entries, list) or not entries or len(entries) > MAX_PIN_FILES):
        raise TransferError("The retained restore file inventory is invalid.")
    for path in roots.values():
        _absolute_root(path)
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"root", "key", "sha256", "size"}
                or not isinstance(entry["root"], str) or entry["root"] not in roots
                or not isinstance(entry["sha256"], str) or not _SHA256.fullmatch(entry["sha256"])
                or type(entry["size"]) is not int or entry["size"] < 0):
            raise TransferError("The retained restore file inventory is invalid.")
        validate_key(entry["key"])
        identity = (entry["root"], entry["key"])
        if identity in seen:
            raise TransferError("The retained restore file inventory repeats a destination.")
        seen.add(identity)
    return document


def pin_restore_files(operation, restore_plan):
    """Persist exact restore/reuse retention before any files are published."""
    entries = tuple(restore_plan.archive.entries)
    if not entries:
        return None
    operation_id = _operation_id(operation.get("id"))
    destination = (operation.get("destination") or {}).get("database")
    destination = destination or (operation.get("result") or {}).get("target_database")
    destination = destination or getattr(settings, "QC_TOOL_RESTORE_DATABASE", "")
    document = _validate({
        "version": VERSION, "operation_id": operation_id,
        "destination_database": destination,
        "roots": {name: _absolute_root(Path(path)) for name, path in restore_plan.roots.items()},
        "files": [{key: entry[key] for key in ("root", "key", "sha256", "size")} for entry in entries],
    }, operation_id)
    path = store.operation_dir(operation_id) / FILENAME
    try:
        if os.path.lexists(path):
            if _validate(store.read_json(path), operation_id) != document:
                raise TransferError("The retained restore storage pin changed. Preserve its files and reconcile the operation before continuing.")
            return document
        store.write_json(path, document)
    except OSError as error:
        raise TransferError("The retained database's files could not be protected durably. No new files may be published.") from error
    return document


def _current_root(area_key):
    if area_key == "incoming":
        return Path(settings.MEDIA_ROOT)
    if area_key == "jobs":
        return Path(CONFIG["work_dir"])
    if area_key in {"published", "submissions"}:
        configured = CONFIG.get("submission_dir")
        return Path(configured) if configured else None
    if area_key == "boundaries":
        configured = CONFIG.get("boundary_dir")
        return Path(configured) if configured else None
    # Other Admin areas are immutable and have no retirement workflow.
    return None


def describe_pins(area_key, relative_path, *, is_directory=False):
    """Read retained-file protection without creating journals or querying SQL."""
    root = _current_root(area_key)
    if root is None:
        return []
    validate_key(relative_path)
    target = Path(_absolute_root(root)) / relative_path
    private_root = store._directory_path()
    try:
        _private_directory(private_root)
    except FileNotFoundError:
        return []
    except OSError as error:
        raise TransferError("Retained database file protection cannot be inspected safely.") from error
    references, scanned_entries, scanned_files, scanned_bytes = [], 0, 0, 0
    try:
        with os.scandir(private_root) as operations:
            for item in operations:
                scanned_entries += 1
                if scanned_entries > MAX_SCAN_OPERATIONS:
                    raise TransferError("Retained database file protection exceeds its safe inspection bound.")
                if item.name in {"execution.lock", "database-selection.json"} and item.is_file(follow_symlinks=False):
                    continue
                operation_id = _operation_id(item.name)
                directory = private_root / operation_id
                _private_directory(directory)
                path = directory / FILENAME
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                scanned_bytes += metadata.st_size
                if scanned_bytes > MAX_SCAN_BYTES:
                    raise TransferError("Retained database file protection exceeds its safe inspection bound.")
                document = _validate(store.read_json(path), operation_id)
                scanned_files += len(document["files"])
                if scanned_files > MAX_SCANNED_FILES:
                    raise TransferError("Retained database file protection exceeds its safe inspection bound.")
                matched = False
                for entry in document["files"]:
                    candidate = Path(document["roots"][entry["root"]]) / entry["key"]
                    if candidate == target or (is_directory and target in candidate.parents):
                        matched = True
                        break
                if matched:
                    references.append({"kind": "retained_restore", "id": operation_id,
                        "label": "Retained restore database: " + document["destination_database"],
                        "url": reverse("admin_data_transfer") + "?" + urlencode({"operation": operation_id})})
    except OSError as error:
        raise TransferError("Retained database file protection cannot be inspected safely.") from error
    return references
