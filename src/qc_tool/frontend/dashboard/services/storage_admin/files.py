"""Descriptor-confined inspection of three explicitly owned storage areas."""

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

from django.conf import settings

from qc_tool.common import CONFIG


MAX_SCAN_ENTRIES = 10_000
MAX_PATH_DEPTH = 32
TRASH_DIRECTORY = ".qc-tool-trash"
_JOB = re.compile(r"job_[0-9a-f]{32}\Z")
_STDOUT = re.compile(r"job\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.stdout\Z")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StorageError(ValueError):
    def __init__(self, message, *, code="storage_unavailable", status_code=409):
        super().__init__(message)
        self.message, self.code, self.status_code = message, code, status_code


def _configuration(area):
    if area == "incoming":
        return "Delivery uploads", Path(settings.MEDIA_ROOT), False
    if area == "jobs":
        return "QC job artifacts", Path(CONFIG["work_dir"]), False
    if area == "published":
        configured = CONFIG.get("submission_dir")
        return "Published submissions", Path(configured) if configured else None, True
    raise StorageError("Choose a supported storage area.", code="invalid_area", status_code=404)


def _protected_locations(area):
    work = Path(CONFIG["work_dir"])
    protected = [CONFIG.get("boundary_dir"), work / "product_definitions", work / "s3_credentials",
                 work / "worker.token", work / "maintenance", work / "data-transfer",
                 getattr(settings, "QC_TOOL_MAINTENANCE_DIR", None),
                 getattr(settings, "QC_TOOL_TRANSFER_DIR", None),
                 getattr(settings, "S3_CREDENTIALS_DIR", None), *(CONFIG.get("product_dirs") or ())]
    if area != "incoming":
        protected.append(settings.MEDIA_ROOT)
    if area != "published":
        protected.append(CONFIG.get("submission_dir"))
    return tuple(Path(os.path.abspath(str(value))) for value in protected if value)


def _protected_root(root, area):
    if not root.is_absolute() or ".." in root.parts:
        raise StorageError("Storage requires an absolute, confined configured directory.")
    if area == "jobs":
        return
    work = Path(os.path.abspath(str(CONFIG["work_dir"])))
    if root == work or root in work.parents:
        raise StorageError("This storage area would expose protected application storage.")
    for path in _protected_locations(area):
        if root == path or root in path.parents or path in root.parents:
            raise StorageError("This storage area overlaps protected application storage.")


def _parts(area, path="", *, allow_empty=True):
    _configuration(area)
    if not isinstance(path, str) or len(path.encode("utf-8", errors="replace")) > 4096:
        raise StorageError("Choose a valid relative storage path.", code="invalid_path", status_code=400)
    if not path:
        if allow_empty:
            return ()
        raise StorageError("Choose a file inside this storage area.", code="invalid_path", status_code=400)
    parts = tuple(path.split("/"))
    if len(parts) > MAX_PATH_DEPTH or any(
        not part or part.startswith(".") or "\\" in part
        or len(part.encode("utf-8", errors="replace")) > 255
        or unicodedata.normalize("NFC", part) != part
        or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in part)
        for part in parts
    ):
        raise StorageError("Choose a valid relative storage path; hidden files and traversal are unavailable.",
                           code="invalid_path", status_code=400)
    if area == "jobs" and not (_JOB.fullmatch(parts[0]) or (len(parts) == 1 and _STDOUT.fullmatch(parts[0]))):
        raise StorageError("Only reviewed QC job directories and stdout files are available.", code="invalid_path", status_code=404)
    if area == "jobs":
        target = Path(CONFIG["work_dir"]) / parts[0]
        if any(target == protected or target in protected.parents or protected in target.parents
               for protected in _protected_locations(area)):
            raise StorageError("This QC job path overlaps protected application storage.", status_code=404)
    return parts


@contextmanager
def root_descriptor(area):
    label, root, read_only = _configuration(area)
    if root is None:
        raise StorageError("Published submission storage is not configured.")
    _protected_root(root, area)
    descriptor = None
    try:
        descriptor = os.open(root.anchor, _DIRECTORY_FLAGS)
        for component in root.parts[1:]:
            following = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    except OSError as error:
        raise StorageError("This storage area is unavailable or contains an unsafe directory link.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def directory_descriptor(area, parts=()):
    with root_descriptor(area) as root:
        descriptor = os.dup(root)
        try:
            for component in parts:
                following = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            yield descriptor
        except OSError as error:
            raise StorageError("This folder is unavailable or unsafe.", status_code=404) from error
        finally:
            os.close(descriptor)


def entry_fingerprint(status):
    """Bind a reviewed entry to descriptor identity, content size and timestamps."""
    values = [status.st_dev, status.st_ino, status.st_mode, status.st_size,
              status.st_mtime_ns, status.st_ctime_ns]
    return sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _entry(area, path, status):
    regular, directory = stat.S_ISREG(status.st_mode), stat.S_ISDIR(status.st_mode)
    if not (regular or directory) or (regular and status.st_nlink != 1):
        raise StorageError("Symbolic links, hard-linked files and special files are unavailable.")
    if area == "jobs" and "/" not in path and (
        (_JOB.fullmatch(path) and not directory) or (_STDOUT.fullmatch(path) and not regular)
    ):
        raise StorageError("The QC job storage entry does not match its reviewed layout.")
    return {"name": path.rsplit("/", 1)[-1], "path": path,
            "kind": "directory" if directory else "file", "size_bytes": status.st_size if regular else None,
            "modified_at": datetime.fromtimestamp(status.st_mtime, timezone.utc).isoformat(),
            "fingerprint": entry_fingerprint(status), "downloadable": regular}


def storage_areas():
    result = []
    for key in ("incoming", "jobs", "published"):
        label, _path, read_only = _configuration(key)
        try:
            with root_descriptor(key):
                pass
            available, message = True, ""
        except StorageError as error:
            available, message = False, str(error)
        result.append({"key": key, "label": label, "read_only": read_only,
                       "available": available, "message": message})
    return result


def inspect_entry(area, path):
    parts = _parts(area, path, allow_empty=False)
    with directory_descriptor(area, parts[:-1]) as parent:
        try:
            status = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            raise StorageError("This file or folder is unavailable.", status_code=404) from error
        entry = _entry(area, path, status)
    return {**entry, "area": area}


def list_entries(area, path="", *, page=1, page_size=50, query=""):
    parts = _parts(area, path)
    page_size = min(max(page_size if type(page_size) is int else 50, 1), 100)
    try:
        page = max(int(page), 1)
    except (ValueError, TypeError):
        page = 1
    query = str(query or "")[:150].casefold()
    entries, limited, scanned = [], False, 0
    with directory_descriptor(area, parts) as directory:
        with os.scandir(directory) as iterator:
            for item in iterator:
                scanned += 1
                if scanned > MAX_SCAN_ENTRIES:
                    limited = True
                    break
                relative = "/".join((*parts, item.name))
                try:
                    _parts(area, relative, allow_empty=False)
                    if query and query not in item.name.casefold():
                        continue
                    entries.append(_entry(area, relative, item.stat(follow_symlinks=False)))
                except (StorageError, OSError, ValueError, OverflowError):
                    continue
    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold(), item["name"]))
    total = len(entries)
    page = min(page, max((total + page_size - 1) // page_size, 1))
    return {"area": area, "path": path, "entries": entries[(page - 1) * page_size:page * page_size],
            "page": page, "has_previous": page > 1, "has_next": page * page_size < total,
            "total": total, "scan_limited": limited}


def _open_file_at(area, path, parent, name):
    descriptor = None
    try:
        descriptor = os.open(name, _FILE_FLAGS, dir_fd=parent)
        _entry(area, path, os.fstat(descriptor))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StorageError("Choose a regular file to download.")
        handle = os.fdopen(descriptor, "rb")
        descriptor = None
        return handle
    except OSError as error:
        raise StorageError("This file is unavailable or unsafe.", status_code=404) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def open_file(area, path):
    parts = _parts(area, path, allow_empty=False)
    with directory_descriptor(area, parts[:-1]) as parent:
        return _open_file_at(area, path, parent, parts[-1])


def quarantine_reason(area, path, entry):
    if area == "published":
        return "Published submissions and their immutable receipts cannot be moved to trash."
    if entry["kind"] != "file":
        return "Only individual unreferenced files can be moved to trash."
    parts = _parts(area, path, allow_empty=False)
    if area == "incoming":
        return "" if parts[-1].casefold().endswith(".zip") else "Only delivery ZIP files can be moved to trash here."
    if len(parts) == 1 and _STDOUT.fullmatch(parts[0]):
        return ""
    if len(parts) >= 3 and parts[1] == "output.d":
        return ""
    report_name = parts[-1].casefold()
    if len(parts) == 2 and (parts[1] == "job.log" or report_name == "report.pdf"
                            or report_name.endswith("_report.pdf")):
        return ""
    return "Job inputs, temporary state, result metadata and original specification snapshots are protected."
