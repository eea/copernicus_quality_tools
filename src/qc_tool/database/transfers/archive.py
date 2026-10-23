"""Bounded, data-only record packages; never extract an uploaded archive.

The ZIP container is deliberately separate from the application record contract.
Readers verify its complete inventory before any record or file is published.
Checksums establish integrity, not the identity or trustworthiness of a sender.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tempfile
import unicodedata
import zipfile

from .contracts import TransferError


FORMAT = "qc-tool-record-transfer"
FORMAT_VERSION = 1
BLOCK_SIZE = 1024 * 1024
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ROOT = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


class TransferArchiveError(TransferError):
    """A package cannot be processed without risking data or resource safety."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 16 * 1024**3
    max_total_bytes: int = 64 * 1024**3
    max_member_bytes: int = 16 * 1024**3
    max_records_bytes: int = 128 * 1024**2
    max_manifest_bytes: int = 16 * 1024**2
    max_members: int = 100_000
    max_central_directory_bytes: int = 64 * 1024**2
    max_compression_ratio: float = 1000.0

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name == "max_compression_ratio":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 1:
                    raise ValueError("Invalid archive compression limit.")
            elif isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Archive limits must be positive integers.")


@dataclass(frozen=True)
class ArtifactSource:
    root: str
    key: str
    path: Path
    storage_root: Path | None = None


def validate_key(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise TransferArchiveError("An archive path is invalid.")
    path = PurePosixPath(value)
    if (
        path.is_absolute() or path.as_posix() != value or len(path.parts) > 32
        or any(part in {"", ".", ".."} or len(part.encode("utf-8")) > 255 for part in path.parts)
        or "\\" in value or ":" in value
        or unicodedata.normalize("NFC", value) != value
        or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)
    ):
        raise TransferArchiveError("An archive path is unsafe.")
    return value


def _root(value):
    if not isinstance(value, str) or not _ROOT.fullmatch(value):
        raise TransferArchiveError("An artifact storage root is invalid.")
    return value


def canonical_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise TransferArchiveError("Package metadata must contain valid JSON data.") from exc


def _json(payload):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise TransferArchiveError("Duplicate JSON keys are not supported.")
            result[name] = value
        return result

    def invalid(_value):
        raise TransferArchiveError("Non-finite JSON numbers are not supported.")

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise TransferArchiveError("Package metadata is not valid JSON.") from exc


@contextmanager
def open_regular(path, *, storage_root=None):
    """Open a regular file, refusing links in every storage-relative component."""

    path = Path(path)
    if storage_root is None:
        storage_root, parts = path.parent, (path.name,)
    else:
        storage_root = Path(storage_root)
        try:
            parts = path.relative_to(storage_root).parts
        except ValueError as exc:
            raise TransferArchiveError("An artifact escaped its configured storage root.") from exc
    if not parts or any(part in {".", ".."} for part in parts):
        raise TransferArchiveError("An artifact path is invalid.")
    descriptor = None
    current = None
    try:
        current = os.open(storage_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TransferArchiveError("An artifact is not a regular file.")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            yield stream
    except OSError as exc:
        raise TransferArchiveError("An artifact is unavailable or contains a filesystem link.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if current is not None:
            os.close(current)


def _hash(stream, limit, output=None):
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: stream.read(BLOCK_SIZE), b""):
        size += len(block)
        if size > limit:
            raise TransferArchiveError("A package member exceeds its size limit.")
        digest.update(block)
        if output is not None:
            output.write(block)
    return digest.hexdigest(), size


def _descriptor(path, digest, size):
    return {"path": path, "sha256": digest, "size": size}


def _validate_descriptor(entry):
    if not isinstance(entry, dict) or not {"path", "sha256", "size"}.issubset(entry):
        raise TransferArchiveError("The archive inventory is invalid.")
    validate_key(entry["path"])
    if not isinstance(entry["sha256"], str) or not _DIGEST.fullmatch(entry["sha256"]):
        raise TransferArchiveError("The archive inventory checksum is invalid.")
    if type(entry["size"]) is not int or entry["size"] < 0:
        raise TransferArchiveError("The archive inventory size is invalid.")


def _validate_names(names):
    lowered = set()
    for name in names:
        validate_key(name)
        folded = name.casefold()
        if folded in lowered:
            raise TransferArchiveError("The archive contains duplicate or case-colliding paths.")
        lowered.add(folded)
    for name in lowered:
        parts = PurePosixPath(name).parts
        if any("/".join(parts[:index]) in lowered for index in range(1, len(parts))):
            raise TransferArchiveError("The archive contains a file/directory path collision.")


def write_archive(path, manifest, records, artifacts=(), *, directories=(), storage=None, limits=None,
                  expected_artifacts=None):
    """Create a private, fsynced package without replacing an existing file."""

    limits = limits or ArchiveLimits()
    if not isinstance(manifest, dict) or "archive" in manifest or not isinstance(records, (list, dict)):
        raise TransferArchiveError("The application package metadata is invalid.")
    records_bytes = canonical_json(records)
    if len(records_bytes) > limits.max_records_bytes:
        raise TransferArchiveError("The record payload exceeds its size limit.")
    sources = tuple(artifacts)
    entries = []
    for source in sources:
        root, key = _root(source.root), validate_key(source.key)
        with open_regular(source.path, storage_root=source.storage_root) as stream:
            digest, size = _hash(stream, limits.max_member_bytes)
        entries.append({"root": root, "key": key, **_descriptor("artifacts/" + root + "/" + key, digest, size)})
    if expected_artifacts is not None:
        actual = [{key: entry[key] for key in ("root", "key", "sha256", "size")} for entry in entries]
        if actual != list(expected_artifacts):
            raise TransferArchiveError("The files changed after review. Review the export again.")
    directory_entries = [{"root": _root(item["root"]), "key": validate_key(item["key"])} for item in directories]
    _validate_names(["manifest.json", "records.json", *(entry["path"] for entry in entries)])
    if len(entries) + 2 > limits.max_members:
        raise TransferArchiveError("The package contains too many members.")
    if sum(item["size"] for item in entries) + len(records_bytes) > limits.max_total_bytes:
        raise TransferArchiveError("The package exceeds its total size limit.")
    envelope = {**manifest, "archive": {
        "format": FORMAT, "version": FORMAT_VERSION,
        "records": _descriptor("records.json", hashlib.sha256(records_bytes).hexdigest(), len(records_bytes)),
        "artifacts": entries, "directories": directory_entries, "storage": storage or {},
    }}
    manifest_bytes = canonical_json(envelope)
    if len(manifest_bytes) > limits.max_manifest_bytes:
        raise TransferArchiveError("The archive inventory exceeds its size limit.")
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".transfer-", suffix=".pending", delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as package:
                package.writestr("manifest.json", manifest_bytes)
                package.writestr("records.json", records_bytes)
                for source, entry in zip(sources, entries):
                    info = zipfile.ZipInfo(entry["path"])
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    # Artifacts can already be compressed; stored bytes avoid both
                    # wasteful recompression and packages our ratio limit rejects.
                    info.compress_type = zipfile.ZIP_STORED
                    with open_regular(source.path, storage_root=source.storage_root) as stream, package.open(info, "w", force_zip64=True) as member:
                        actual = _hash(stream, limits.max_member_bytes, member)
                    if actual != (entry["sha256"], entry["size"]):
                        raise TransferArchiveError("An artifact changed while the package was being created.")
            output.flush()
            os.fsync(output.fileno())
            if output.tell() > limits.max_archive_bytes:
                raise TransferArchiveError("The archive exceeds its size limit.")
        os.link(temporary, path)
        _sync_directory(path.parent)
        with open_regular(path) as stream:
            return _hash(stream, limits.max_archive_bytes)[0]
    except OSError as exc:
        raise TransferArchiveError("The package could not be published without overwriting existing data.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _check_central_directory(stream, size, limits):
    """Bound ZIP metadata before ZipFile allocates its member objects."""

    stream.seek(max(0, size - 65_557))
    tail = stream.read(65_557)
    index = tail.rfind(b"PK\x05\x06")
    if index < 0 or len(tail) - index < 22:
        raise TransferArchiveError("The package is not a complete ZIP archive.")
    fields = struct.unpack("<4s4H2LH", tail[index:index + 22])
    if index + 22 + fields[-1] != len(tail) or fields[1] or fields[2] or fields[3] != fields[4]:
        raise TransferArchiveError("Split or ambiguous ZIP archives are unsupported.")
    count, directory_size = fields[4], fields[5]
    if count == 0xFFFF or directory_size == 0xFFFFFFFF or fields[6] == 0xFFFFFFFF:
        absolute = size - len(tail) + index
        if absolute < 20:
            raise TransferArchiveError("ZIP64 metadata is incomplete.")
        stream.seek(absolute - 20)
        locator = struct.unpack("<4sLQL", stream.read(20))
        if locator[0] != b"PK\x06\x07" or locator[1] != 0 or locator[3] != 1:
            raise TransferArchiveError("ZIP64 metadata is unsupported.")
        stream.seek(locator[2])
        raw = stream.read(56)
        if len(raw) != 56:
            raise TransferArchiveError("ZIP64 metadata is incomplete.")
        extended = struct.unpack("<4sQ2H2L4Q", raw)
        if extended[0] != b"PK\x06\x06" or extended[4] or extended[5] or extended[6] != extended[7]:
            raise TransferArchiveError("Split ZIP64 packages are unsupported.")
        count, directory_size = extended[7], extended[8]
    if count > limits.max_members or directory_size > limits.max_central_directory_bytes:
        raise TransferArchiveError("The archive contains too much ZIP metadata.")
    stream.seek(0)


@dataclass(frozen=True)
class VerifiedArchive:
    path: Path
    manifest: dict
    records: list | dict
    entries: tuple
    directories: tuple
    storage: dict
    package_sha256: str
    limits: ArchiveLimits

    @contextmanager
    def open_artifact(self, entry):
        """Reopen private staging bytes; caller must verify the copied digest."""

        if entry not in self.entries:
            raise TransferArchiveError("An artifact is not in the verified inventory.")
        try:
            with open_regular(self.path) as source, zipfile.ZipFile(source) as package, package.open(entry["path"]) as member:
                yield member
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise TransferArchiveError("A staged package artifact is unavailable.") from exc

    def copy_artifact(self, entry, output):
        with self.open_artifact(entry) as source:
            actual = _hash(source, min(entry["size"], self.limits.max_member_bytes), output)
        if actual != (entry["sha256"], entry["size"]):
            raise TransferArchiveError("A staged artifact failed integrity verification.")


def inspect_archive(path, *, limits=None):
    """Validate complete ZIP inventory and hashes without extracting any member."""

    limits = limits or ArchiveLimits()
    path = Path(path)
    try:
        with open_regular(path) as source:
            size = os.fstat(source.fileno()).st_size
            if size > limits.max_archive_bytes:
                raise TransferArchiveError("The archive exceeds its size limit.")
            _check_central_directory(source, size, limits)
            with zipfile.ZipFile(source) as package:
                infos = package.infolist()
                _validate_names([item.filename for item in infos])
                if len(infos) > limits.max_members:
                    raise TransferArchiveError("The archive contains too many members.")
                total = 0
                for item in infos:
                    mode = item.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if item.is_dir() or kind not in (0, stat.S_IFREG) or item.flag_bits & 1 or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise TransferArchiveError("Only unencrypted regular data files are supported.")
                    if item.file_size > limits.max_member_bytes or item.file_size > max(1, item.compress_size) * limits.max_compression_ratio:
                        raise TransferArchiveError("An archive member exceeds its resource limit.")
                    total += item.file_size
                if total > limits.max_total_bytes:
                    raise TransferArchiveError("The archive exceeds its total size limit.")
                metadata = {}
                for name, limit in (("manifest.json", limits.max_manifest_bytes), ("records.json", limits.max_records_bytes)):
                    try:
                        if package.getinfo(name).file_size > limit:
                            raise TransferArchiveError("Package metadata exceeds its size limit.")
                        with package.open(name) as stream:
                            payload = stream.read(limit + 1)
                        if len(payload) > limit:
                            raise TransferArchiveError("Package metadata exceeds its size limit.")
                        metadata[name] = payload
                    except KeyError as exc:
                        raise TransferArchiveError("The package is missing required metadata.") from exc
                manifest = _json(metadata["manifest.json"])
                records = _json(metadata["records.json"])
                if not isinstance(manifest, dict) or not isinstance(records, (list, dict)):
                    raise TransferArchiveError("Package metadata has an unsupported shape.")
                envelope = manifest.pop("archive", None)
                if not isinstance(envelope, dict) or set(envelope) != {"format", "version", "records", "artifacts", "directories", "storage"} or envelope.get("format") != FORMAT or type(envelope.get("version")) is not int or envelope["version"] != FORMAT_VERSION:
                    raise TransferArchiveError("This package format version is unsupported.")
                record_entry = envelope.get("records")
                _validate_descriptor(record_entry)
                if set(record_entry) != {"path", "sha256", "size"} or record_entry["path"] != "records.json" or (record_entry["sha256"], record_entry["size"]) != (hashlib.sha256(metadata["records.json"]).hexdigest(), len(metadata["records.json"])):
                    raise TransferArchiveError("The record payload failed integrity validation.")
                entries = envelope.get("artifacts")
                directories = envelope.get("directories")
                storage = envelope.get("storage")
                if not isinstance(entries, list) or not isinstance(directories, list) or not isinstance(storage, dict):
                    raise TransferArchiveError("The artifact inventory is invalid.")
                for entry in entries:
                    _validate_descriptor(entry)
                    if set(entry) != {"root", "key", "path", "size", "sha256"} or entry["path"] != "artifacts/" + _root(entry["root"]) + "/" + validate_key(entry["key"]):
                        raise TransferArchiveError("An artifact destination is invalid.")
                directory_names = []
                for entry in directories:
                    if not isinstance(entry, dict) or set(entry) != {"root", "key"}:
                        raise TransferArchiveError("A directory inventory entry is invalid.")
                    directory_names.append("artifacts/" + _root(entry["root"]) + "/" + validate_key(entry["key"]))
                _validate_names([entry["path"] for entry in entries])
                if len(set(name.casefold() for name in directory_names)) != len(directory_names):
                    raise TransferArchiveError("Directory inventory entries collide.")
                file_names = {entry["path"].casefold() for entry in entries}
                for name in directory_names:
                    parts = PurePosixPath(name.casefold()).parts
                    if any("/".join(parts[:index]) in file_names for index in range(1, len(parts) + 1)):
                        raise TransferArchiveError("File and directory inventory paths collide.")
                expected = {"manifest.json", "records.json", *(entry["path"] for entry in entries)}
                if {item.filename for item in infos} != expected:
                    raise TransferArchiveError("The archive contains unlisted or missing files.")
                for entry in entries:
                    with package.open(entry["path"]) as member:
                        actual = _hash(member, min(entry["size"], limits.max_member_bytes))
                    if actual != (entry["sha256"], entry["size"]):
                        raise TransferArchiveError("An artifact failed integrity validation.")
            source.seek(0)
            digest, _ = _hash(source, limits.max_archive_bytes)
        return VerifiedArchive(path, manifest, records, tuple(entries), tuple(directories), storage, digest, limits)
    except TransferArchiveError:
        raise
    except (OSError, ValueError, EOFError, struct.error, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise TransferArchiveError("The package is damaged or uses an unsupported ZIP encoding.") from exc
