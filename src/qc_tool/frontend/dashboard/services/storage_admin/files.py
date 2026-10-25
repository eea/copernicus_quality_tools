"""Descriptor-confined browsing of configured application storage mounts.

The browser is a file reader, not a host filesystem explorer. Area identities
come from deployment configuration, and private control/credential storage is
never made available through a broader working-directory root.
"""

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
from qc_tool.frontend.dashboard.services.boundaries.layout import TRASH_DIRECTORY_NAME as BOUNDARY_TRASH_DIRECTORY


MAX_SCAN_ENTRIES = 10_000
MAX_PATH_DEPTH = 32
TRASH_DIRECTORY = ".qc-tool-trash"
_JOB = re.compile(r"job_[0-9a-f]{32}\Z")
_STDOUT = re.compile(r"job\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.stdout\Z")
# These hidden directories hold immutable content, rather than runtime state.
# Recognize their real configured paths through every physical browser alias.
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StorageError(ValueError):
    def __init__(self, message, *, code="storage_unavailable", status_code=409):
        super().__init__(message)
        self.message, self.code, self.status_code = message, code, status_code


def _areas():
    work = Path(CONFIG["work_dir"])
    definitions = [
        ("work", "Application files", work, True,
         "Browse working folders, retained files, reports and logs."),
        ("incoming", "Delivery uploads", Path(settings.MEDIA_ROOT), False,
         "Original delivery ZIPs, grouped by uploader."),
        ("jobs", "QC job artifacts", work, False,
         "Retained job inputs, outputs, reports and logs, grouped by job."),
        ("published", "Published submissions", CONFIG.get("submission_dir"), True,
         "Files retained as published submission evidence."),
        ("boundaries", "Boundaries", CONFIG.get("boundary_dir"), True,
         "Original boundary files and their supporting data."),
        ("uploaded-specifications", "Product specifications", work / "product_definitions", True,
         "Saved original product specification versions."),
    ]
    persistent_root = getattr(settings, "QC_TOOL_PERSISTENT_STORAGE_ROOT", "")
    if persistent_root:
        definitions.insert(0, ("persistent", "Persistent storage", Path(persistent_root), True,
                              "Shared application files on this installation's persistent storage."))
    product_dirs = CONFIG.get("product_dirs") or ()
    for index, directory in enumerate(product_dirs):
        definitions.append((f"spec-{index}", "Product specifications", directory, True,
                            "Original product specification files provided with the deployment."))
    extra_roots = getattr(settings, "QC_TOOL_STORAGE_ROOTS", ())
    if not isinstance(extra_roots, (list, tuple)) or len(extra_roots) > 16:
        raise StorageError("Additional storage roots require a reviewed operator configuration.")
    keys = set()
    for extra in extra_roots:
        if (not isinstance(extra, dict) or not isinstance(extra.get("key"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", extra["key"])
                or extra["key"] in keys or not isinstance(extra.get("label"), str)
                or not extra["label"].strip() or len(extra["label"]) > 100
                or not isinstance(extra.get("path"), (str, Path))):
            raise StorageError("Additional storage roots require a reviewed operator configuration.")
        keys.add(extra["key"])
        root = Path(extra["path"])
        if not root.is_absolute() or ".." in root.parts:
            raise StorageError("Additional storage requires absolute, confined configured directories.")
        definitions.append(("extra-" + extra["key"], extra["label"], root, True,
                            "Additional server storage configured for this installation."))
    return {key: {"key": key, "label": label, "root": Path(root) if root else None,
                  "read_only": read_only, "can_trash": key in {"incoming", "jobs"},
                  "group": "installation" if key.startswith("spec-") else "storage",
                  "collection": "specifications" if key == "uploaded-specifications" or key.startswith("spec-") else "",
                  "description": description}
            for key, label, root, read_only, description in definitions}


def area_info(area):
    """Public root metadata, without physical paths or filesystem probes."""
    try:
        return {key: value for key, value in _areas()[area].items() if key != "root"}
    except (KeyError, TypeError) as error:
        raise StorageError("Choose a supported storage area.", code="invalid_area", status_code=404) from error


def _configuration(area):
    area_info(area)
    definition = _areas()[area]
    return definition["label"], definition["root"], definition["read_only"]


def _private_locations():
    work = Path(CONFIG["work_dir"])
    private = [work / "s3_credentials", work / "worker.token", work / "maintenance", work / "data-transfer",
               getattr(settings, "QC_TOOL_MAINTENANCE_DIR", None),
               getattr(settings, "QC_TOOL_TRANSFER_DIR", None),
               getattr(settings, "S3_CREDENTIALS_DIR", None),
               getattr(settings, "FILE_UPLOAD_TEMP_DIR", None)]
    # A locally configured SQLite database is never an ordinary downloadable
    # file; a coherent complete backup belongs to the Database workflow.
    databases = [CONFIG.get("frontend_db_path")]
    for database in getattr(settings, "DATABASES", {}).values():
        if database.get("ENGINE") == "django.db.backends.sqlite3":
            databases.append(database.get("NAME"))
        options = database.get("OPTIONS") or {}
        private.extend(options.get(name) for name in ("sslkey", "sslcert", "sslrootcert", "sslcrl"))
    for database in databases:
        if database and str(database) != ":memory:":
            private.extend(str(database) + suffix for suffix in ("", "-wal", "-shm", "-journal"))
    return tuple(Path(os.path.abspath(str(value))) for value in private if value)


def _content_locations():
    locations = [Path(CONFIG["work_dir"]) / "product_definitions" / ".versions"]
    if CONFIG.get("boundary_dir"):
        locations.append(Path(CONFIG["boundary_dir"]) / ".boundary-generations")
    return frozenset(Path(os.path.abspath(str(value))) for value in locations)


def _control_locations():
    root = Path(CONFIG["work_dir"]) / "product_definitions"
    locations = [root / ".state", root / ".upload.lock"]
    if CONFIG.get("boundary_dir"):
        boundary = Path(CONFIG["boundary_dir"])
        locations.extend(boundary / name for name in (".boundary-current", ".boundary-package.lock", BOUNDARY_TRASH_DIRECTORY))
    return tuple(Path(os.path.abspath(str(value))) for value in locations)


def _content_path(root, parts):
    return root is not None and Path(os.path.abspath(str(root.joinpath(*parts)))) in _content_locations()


def _protected_locations(area):
    work = Path(CONFIG["work_dir"])
    protected = [*_private_locations(), CONFIG.get("boundary_dir"), work / "product_definitions",
                 *(CONFIG.get("product_dirs") or ())]
    if area != "incoming":
        protected.append(settings.MEDIA_ROOT)
    if area != "published":
        protected.append(CONFIG.get("submission_dir"))
    return tuple(Path(os.path.abspath(str(value))) for value in protected if value)


def _protected_root(root, area):
    if not root.is_absolute() or ".." in root.parts:
        raise StorageError("Storage requires an absolute, confined configured directory.")
    if any(root == control or control in root.parents for control in _control_locations()):
        raise StorageError("This storage area overlaps private application control files.")
    work = Path(os.path.abspath(str(CONFIG["work_dir"])))
    if area in {"jobs", "work", "persistent"}:
        if any(root == private or private in root.parents for private in _private_locations()):
            raise StorageError("This storage area overlaps private application storage.")
        return
    if root == work or root in work.parents:
        raise StorageError("This storage area would expose protected application storage.")
    protected = _protected_locations(area) if area in {"incoming", "published"} else _private_locations()
    for path in protected:
        if root == path or root in path.parents or path in root.parents:
            raise StorageError("This storage area overlaps protected application storage.")


def _parts(area, path="", *, allow_empty=True):
    _label, root, _read_only = _configuration(area)
    if not isinstance(path, str) or len(path.encode("utf-8", errors="replace")) > 4096:
        raise StorageError("Choose a valid relative storage path.", code="invalid_path", status_code=400)
    if not path:
        if allow_empty:
            return ()
        raise StorageError("Choose a file inside this storage area.", code="invalid_path", status_code=400)
    parts = tuple(path.split("/"))
    if len(parts) > MAX_PATH_DEPTH or any(
        not part or part in {".", ".."} or (part.startswith(".") and not
            _content_path(root, parts[:index + 1])) or "\\" in part
        or len(part.encode("utf-8", errors="replace")) > 255
        or unicodedata.normalize("NFC", part) != part
        or any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in part)
        for index, part in enumerate(parts)
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
    # Check every path, including directly requested downloads and descendants
    # of otherwise ordinary folders. A configured private child never becomes
    # visible by navigating through its parent in the general work browser.
    if root is not None:
        target = Path(os.path.abspath(str(root.joinpath(*parts))))
        if any(target == private or private in target.parents
               for private in (*_private_locations(), *_control_locations())):
            raise StorageError("Private credentials and application control files are protected.",
                               code="protected_storage", status_code=404)
    return parts


@contextmanager
def root_descriptor(area):
    label, root, read_only = _configuration(area)
    if root is None:
        raise StorageError(f"{label} storage is not configured.")
    _check_persistent_storage()
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


def _check_persistent_storage():
    """Use the startup storage identity contract for live browser reads too."""
    root = getattr(settings, "QC_TOOL_PERSISTENT_STORAGE_ROOT", "")
    identity = getattr(settings, "QC_TOOL_PERSISTENT_STORAGE_ID", "")
    if not root and not identity:
        return
    from qc_tool.storage.guard import check_storage, StorageConfigurationError
    environment = {"QC_TOOL_PERSISTENT_STORAGE_ROOT": str(root),
                   "QC_TOOL_PERSISTENT_STORAGE_ID": str(identity),
                   "WORK_DIR": str(CONFIG["work_dir"]), "INCOMING_DIR": str(settings.MEDIA_ROOT),
                   "BOUNDARY_DIR": str(CONFIG.get("boundary_dir") or ""),
                   "SUBMISSION_DIR": str(CONFIG.get("submission_dir") or "")}
    try:
        check_storage(environment)
    except StorageConfigurationError as error:
        raise StorageError(str(error), code="persistent_storage_unavailable", status_code=503) from error


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
    if _content_path(_configuration(area)[1], tuple(path.split("/"))) and not directory:
        raise StorageError("This retained content location must be a real directory.")
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
    for key in _areas():
        try:
            with root_descriptor(key):
                pass
            available, message = True, ""
        except StorageError as error:
            available, message = False, str(error)
        result.append({**area_info(key),
                       "available": available, "message": message})
    return result


def storage_path(area, path=""):
    """Actual server/container path for the administrator's address bar.

    This is display metadata, never an arbitrary path accepted by the reader.
    Every request still selects a configured root and a validated relative path.
    """
    parts = _parts(area, path)
    root = _configuration(area)[1]
    return str(root.joinpath(*parts)) if root is not None else ""


def location_label(area):
    info = area_info(area)
    path = storage_path(area)
    return info["label"] if area == "persistent" else Path(path).name or path or info["label"]


def storage_locations():
    """Show each browsable physical tree once, preserving distinct access scopes.

    Available read-only children need no second drive entry when an available
    read-only parent in the same group already exposes their exact path. Backend
    area identities remain valid for existing links and owning workflows.
    """
    result = []
    for area in storage_areas():
        if area["key"] == "jobs":
            continue
        path = storage_path(area["key"])
        purpose = ("Shared application files" if area["key"] == "persistent" else
                   "Saved specification versions" if area["key"] == "uploaded-specifications" else
                   "Specifications shipped with QC Tool" if area["group"] == "installation" else area["label"])
        result.append({**area, "purpose_label": purpose,
                       "label": area["label"] if area["key"] == "persistent" else
                                Path(path).name or path or area["label"], "storage_path": path})
    visible = []
    for index, area in enumerate(result):
        covered = False
        if area["available"] and area["read_only"] and not area["can_trash"]:
            root = Path(area["storage_path"])
            for parent_index, parent in enumerate(result):
                if (parent_index == index or not parent["available"] or not parent["read_only"]
                        or parent["can_trash"] or parent["group"] != area["group"]):
                    continue
                parent_root = Path(parent["storage_path"])
                if root == parent_root and parent_index > index:
                    continue
                if root != parent_root and parent_root not in root.parents:
                    continue
                relative = root.relative_to(parent_root)
                try:
                    _parts(parent["key"], "" if root == parent_root else relative.as_posix())
                except StorageError:
                    continue
                covered = True
                break
        if not covered:
            visible.append(area)
    return visible


def inspect_entry(area, path):
    parts = _parts(area, path, allow_empty=False)
    with directory_descriptor(area, parts[:-1]) as parent:
        try:
            status = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            raise StorageError("This file or folder is unavailable.", status_code=404) from error
        entry = _entry(area, path, status)
    return {**entry, "area": area}


def list_entries(area, path="", *, page=1, page_size=50, query="", sort="name", descending=False):
    parts = _parts(area, path)
    page_size = min(max(page_size if type(page_size) is int else 50, 1), 100)
    try:
        page = max(int(page), 1)
    except (ValueError, TypeError):
        page = 1
    query = str(query or "")[:150].casefold()
    sort = sort if sort in {"name", "modified", "size"} else "name"
    descending = descending is True
    entries, limited, scanned, skipped = [], False, 0, 0
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
                    skipped += 1
                    continue
    # Stable passes preserve alphabetical ties and keep folders first even
    # when ordering largest/newest first.
    entries.sort(key=lambda item: (item["name"].casefold(), item["name"]))
    if sort == "modified":
        entries.sort(key=lambda item: item["modified_at"], reverse=descending)
    elif sort == "size":
        entries.sort(key=lambda item: item["size_bytes"] or 0, reverse=descending)
    elif descending:
        entries.reverse()
    entries.sort(key=lambda item: item["kind"] != "directory")
    total = len(entries)
    page = min(page, max((total + page_size - 1) // page_size, 1))
    return {**area_info(area), "area": area, "path": path,
            "parent_path": path.rpartition("/")[0] if path else None,
            "entries": entries[(page - 1) * page_size:page * page_size],
            "page": page, "has_previous": page > 1, "has_next": page * page_size < total,
            "total": total, "scan_limited": limited, "scanned_count": min(scanned, MAX_SCAN_ENTRIES),
            "skipped_count": skipped, "folder_count": sum(entry["kind"] == "directory" for entry in entries),
            "file_count": sum(entry["kind"] == "file" for entry in entries),
            "visible_bytes": sum(entry["size_bytes"] or 0 for entry in entries),
            "sort": sort, "descending": descending}


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
    if area_info(area)["read_only"]:
        return "This storage area is available for browsing and downloading only."
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
