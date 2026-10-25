"""Bounded, descriptor-confined ZIP downloads without a temporary disk copy.

The inventory is checked before HTTP response headers are sent. File contents are
then read only as the response consumer requests the next chunk. Cancelling the
response closes its current descriptor; no background thread or job is retained.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
import stat
import unicodedata
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from . import files


MAX_SELECTIONS = 100
MAX_ARCHIVE_ENTRIES = 10_000
MAX_PATH_METADATA_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 256 * 1024
REPORT_NAME = "QC_TOOL_DOWNLOAD_INFORMATION.txt"
_WINDOWS_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.IGNORECASE)


@dataclass(frozen=True)
class ZipEntry:
    path: str
    archive_name: str
    kind: str
    size_bytes: int
    modified_at: float
    fingerprint: str


@dataclass(frozen=True)
class ZipExclusion:
    path: str
    reason: str


@dataclass(frozen=True)
class DownloadPlan:
    area: str
    filename: str
    selected_paths: tuple[str, ...]
    entries: tuple[ZipEntry, ...]
    exclusions: tuple[ZipExclusion, ...]
    total_bytes: int
    file_count: int
    directory_count: int

    @property
    def excluded_count(self):
        return len(self.exclusions)


def _portable_name(path):
    """Do not create members that common desktop extractors reinterpret."""
    for part in path.split("/"):
        if part.endswith((".", " ")) or any(character in part for character in ':*?"<>|') or _WINDOWS_RESERVED.fullmatch(part):
            raise files.StorageError("This name cannot be safely extracted by common desktop ZIP tools.")


def _filename(area, selected):
    basename = selected[0].rsplit("/", 1)[-1] if len(selected) == 1 and selected[0] else "storage-" + area
    # Content-Disposition remains simple even when a folder has a long name.
    safe = re.sub(r"[^\w .()-]", "_", basename, flags=re.UNICODE).strip(" .")[:120] or "storage-download"
    return safe + ".zip"


def prepare_zip(area, paths):
    """Review up to 100 selections and 10,000 source entries without reading data.

    Selected paths must be accessible. Unsafe or private *descendants* are omitted
    with an explicit report, so downloading an area never exposes its protected
    control files. Oversized inventories fail rather than silently truncate.
    """
    if isinstance(paths, (str, bytes)):
        raise files.StorageError("Select a folder or files to download.", status_code=400)
    selected = []
    try:
        for index, path in enumerate(paths):
            if index >= MAX_SELECTIONS:
                raise files.StorageError("Select at most 100 items, or download their parent folder.", status_code=400)
            files._parts(area, path)
            if path:
                _portable_name(path)
            if path not in selected:
                selected.append(path)
    except TypeError as error:
        raise files.StorageError("Select a folder or files to download.", status_code=400) from error
    if not selected:
        raise files.StorageError("Select at least one file or folder to download.", status_code=400)
    # A selected parent already includes its descendants. Keep the original
    # selection order for predictable archive layout and remove duplicate work.
    selected = [path for path in selected if not any(
        parent != path and (not parent or path.startswith(parent + "/")) for parent in selected
    )]
    entries, excluded, seen, path_metadata_bytes = [], [], 0, 0
    archive_names = {}

    def count_entry(path):
        nonlocal seen, path_metadata_bytes
        seen += 1
        path_metadata_bytes += len(path.encode("utf-8", errors="replace"))
        if seen > MAX_ARCHIVE_ENTRIES or path_metadata_bytes > MAX_PATH_METADATA_BYTES:
            raise files.StorageError(
                "This download exceeds the 10,000-entry or folder metadata limit. Choose a smaller folder or use the storage connection guide.",
                code="download_too_large", status_code=413,
            )

    def reserve_archive_path(path):
        # Finder and Explorer commonly extract onto case-insensitive filesystems.
        # Check implicit parent folders as well as explicit archive members: two
        # selections such as Foo/a and foo/b must not merge into one folder.
        # A component trie avoids retaining every long parent path repeatedly.
        current = archive_names
        parts = path.split("/")
        for index, component in enumerate(parts):
            key = unicodedata.normalize("NFC", component.casefold())
            previous = current.get(key)
            if previous is None:
                following = {}
                current[key] = (component, following)
            else:
                original, following = previous
                if original != component:
                    old_path = "/".join((*parts[:index], original))
                    new_path = "/".join(parts[:index + 1])
                    raise files.StorageError(
                        f"The names {old_path!r} and {new_path!r} would overlap when extracted in Finder or Explorer. "
                        "Download these items separately or use the storage connection guide to preserve their original names.",
                        code="archive_name_collision", status_code=409,
                    )
            current = following

    def add(path, status):
        entry = files._entry(area, path, status)
        reserve_archive_path(path)
        archive_name = "files/" + path + ("/" if entry["kind"] == "directory" else "")
        entries.append(ZipEntry(path, archive_name, entry["kind"], status.st_size if entry["kind"] == "file" else 0,
                                status.st_mtime, files.entry_fingerprint(status)))
        return entry["kind"]

    def walk(path):
        parts = files._parts(area, path)
        with files.directory_descriptor(area, parts) as directory:
            # os.scandir is consumed once and bounded, including private or unsafe
            # entries. Sorting at most 10,000 names does not depend on data size.
            names = []
            with os.scandir(directory) as iterator:
                for item in iterator:
                    count_entry("/".join((*parts, item.name)))
                    names.append(item.name)
            for name in sorted(names, key=lambda value: (value.casefold(), value)):
                relative = "/".join((*parts, name))
                try:
                    files._parts(area, relative, allow_empty=False)
                    _portable_name(relative)
                    status = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    kind = add(relative, status)
                except (files.StorageError, OSError, ValueError, OverflowError) as error:
                    if isinstance(error, files.StorageError) and error.code == "archive_name_collision":
                        raise
                    # The path is useful for finding an omitted item; neither the
                    # filesystem's absolute path nor secret contents are exposed.
                    excluded.append(ZipExclusion(relative, "Protected, unavailable, linked, special, or non-portable entry."))
                    continue
                if kind == "directory":
                    try:
                        walk(relative)
                    except files.StorageError as error:
                        if error.code in {"download_too_large", "archive_name_collision"}:
                            raise
                        raise files.StorageError("A folder changed or became unavailable while preparing the download. Refresh and try again.") from error

    for path in selected:
        if not path:
            walk("")
            continue
        parts = files._parts(area, path, allow_empty=False)
        count_entry(path)
        with files.directory_descriptor(area, parts[:-1]) as parent:
            try:
                kind = add(path, os.stat(parts[-1], dir_fd=parent, follow_symlinks=False))
            except (OSError, ValueError, OverflowError) as error:
                if isinstance(error, files.StorageError):
                    raise
                raise files.StorageError("A selected item is unavailable. Refresh the folder and try again.", status_code=404) from error
        if kind == "directory":
            walk(path)

    return DownloadPlan(area, _filename(area, selected), tuple(selected), tuple(entries), tuple(excluded),
                        sum(entry.size_bytes for entry in entries), sum(entry.kind == "file" for entry in entries),
                        sum(entry.kind == "directory" for entry in entries))


class _StreamingSink:
    """Unseekable ZipFile target, drained between bounded member writes."""

    def __init__(self):
        self.offset = 0
        self.pending = deque()

    def write(self, data):
        if data:
            self.pending.append(bytes(data))
            self.offset += len(data)
        return len(data)

    def tell(self):
        return self.offset

    def flush(self):
        pass

    def drain(self):
        while self.pending:
            yield self.pending.popleft()


def _zip_info(name, timestamp, *, directory=False, size=0):
    date = datetime.fromtimestamp(timestamp, timezone.utc)
    if date.year < 1980:
        date = datetime(1980, 1, 1)
    elif date.year > 2107:
        date = datetime(2107, 12, 31, 23, 59, 58)
    info = ZipInfo(name, date.timetuple()[:6])
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = ((stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | 0o644)) << 16
    if directory:
        info.external_attr |= 0x10
    info.file_size = size
    return info


def _report(plan):
    lines = ["QC Tool storage download", "", "This is a copy of files, not a database backup.",
             "The files/ folder preserves paths relative to the selected storage area.",
             "For database schema, records and application restore, use Admin > Database > Back up & restore.",
             "", "Storage area: " + plan.area, "Prepared at: " + datetime.now(timezone.utc).isoformat(),
             f"Files: {plan.file_count}", f"Folders: {plan.directory_count}", f"Original file bytes: {plan.total_bytes}",
             "", "Selected paths:"]
    lines.extend("- " + (path or "(storage area root)") for path in plan.selected_paths)
    lines.extend(["", f"Excluded entries: {plan.excluded_count}"])
    if plan.exclusions:
        lines.append("An excluded folder's contents are also excluded. No protected content was read.")
        lines.extend("- " + repr(entry.path) + ": " + entry.reason for entry in plan.exclusions)
    else:
        lines.append("No entries were excluded during preparation.")
    lines.extend(["", "This download is streamed. If a source file changes or the connection ends,",
                  "the ZIP may be incomplete; download it again or use SFTP for resumable transfers.", ""])
    return "\n".join(lines).encode("utf-8")


def stream_zip(plan):
    """Yield a ZIP64 archive, keeping only bounded metadata and a data chunk in RAM.

    Source identity is checked on each opened descriptor before/after reading.
    A changed source aborts the stream instead of returning a valid partial ZIP.
    The caller must close this generator when the response is cancelled.
    """
    sink = _StreamingSink()
    archive = ZipFile(sink, "w", compression=ZIP_STORED, allowZip64=True)
    try:
        archive.writestr(_zip_info("files/", datetime.now(timezone.utc).timestamp(), directory=True), b"")
        yield from sink.drain()
        for entry in plan.entries:
            info = _zip_info(entry.archive_name, entry.modified_at, directory=entry.kind == "directory", size=entry.size_bytes)
            if entry.kind == "directory":
                archive.writestr(info, b"")
                yield from sink.drain()
                continue
            with files.open_file(plan.area, entry.path) as source:
                if files.entry_fingerprint(os.fstat(source.fileno())) != entry.fingerprint:
                    raise files.StorageError("A file changed after the download was prepared. Refresh and download it again.")
                with archive.open(info, "w", force_zip64=True) as destination:
                    yield from sink.drain()
                    remaining = entry.size_bytes
                    while remaining:
                        data = source.read(min(CHUNK_BYTES, remaining))
                        if not data:
                            raise files.StorageError("A file changed during download. Download it again.")
                        remaining -= len(data)
                        destination.write(data)
                        yield from sink.drain()
                    if files.entry_fingerprint(os.fstat(source.fileno())) != entry.fingerprint:
                        raise files.StorageError("A file changed during download. Download it again.")
                yield from sink.drain()
        report = _report(plan)
        archive.writestr(_zip_info(REPORT_NAME, datetime.now(timezone.utc).timestamp(), size=len(report)), report)
        yield from sink.drain()
        archive.close()
        yield from sink.drain()
    finally:
        # ZipFile has no worker; closing a cancelled generator immediately unwinds
        # its current file context. Discard final ZIP metadata on cancellation.
        archive.close()
        sink.pending.clear()
