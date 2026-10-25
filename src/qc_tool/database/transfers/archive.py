"""Bounded, data-only record packages; never extract an uploaded archive.

The ZIP container is deliberately separate from the application record contract.
Readers verify its complete inventory before any record or file is published.
Checksums establish integrity, not the identity or trustworthiness of a sender.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
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
import zlib

from .contracts import TransferError


FORMAT = "qc-tool-record-transfer"
FORMAT_VERSION = 1
NATIVE_FORMAT_VERSION = 2
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
class CompressionPlan:
    """Internal compression measurements bound to the original file bytes.

    The archive inventory continues to describe original bytes only. Plans are
    ephemeral writer hints, never additional trusted fields in a received ZIP.
    """

    sha256: str
    size: int
    compressed_bytes: int
    compress_type: int
    compresslevel: int = 1

    def __post_init__(self):
        if (not isinstance(self.sha256, str) or not _DIGEST.fullmatch(self.sha256)
                or type(self.size) is not int or self.size < 0
                or type(self.compressed_bytes) is not int or self.compressed_bytes < 0
                or self.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or type(self.compress_type) is not int
                or type(self.compresslevel) is not int or self.compresslevel != 1
                or (self.compress_type == zipfile.ZIP_STORED and self.compressed_bytes != self.size)
                or (self.compress_type == zipfile.ZIP_DEFLATED and not 0 < self.compressed_bytes < self.size)):
            raise TransferArchiveError("The file compression plan is invalid.")


@dataclass(frozen=True)
class ArtifactSource:
    root: str
    key: str
    path: Path
    storage_root: Path | None = None
    compression: CompressionPlan | None = None


class CompressionCounter:
    """Measure raw DEFLATE in bounded memory while an existing pass hashes data."""

    def __init__(self):
        self._compressor = zlib.compressobj(1, zlib.DEFLATED, -15)
        self._size = self._compressed = 0
        self._finished = False

    def write(self, block):
        if self._finished:
            raise TransferArchiveError("The file compression measurement is already complete.")
        self._size += len(block)
        self._compressed += len(self._compressor.compress(block))
        return len(block)

    def finish(self, sha256, size, *, limits=None):
        """Use compression only when it saves space and the reader accepts it."""
        if self._finished or size != self._size:
            raise TransferArchiveError("The file compression measurement is invalid.")
        self._compressed += len(self._compressor.flush())
        self._finished = True
        limits = limits or ArchiveLimits()
        compressed = self._compressed
        use_deflate = compressed < size <= max(1, compressed) * limits.max_compression_ratio
        return CompressionPlan(sha256, size, compressed if use_deflate else size,
                               zipfile.ZIP_DEFLATED if use_deflate else zipfile.ZIP_STORED)


def hash_with_compression(stream, limit, *, limits=None, report=None):
    """Hash original bytes and measure their ZIP payload in the same read pass."""
    counter = CompressionCounter()
    checksum, size = _hash(stream, limit, counter, report=report)
    return checksum, size, counter.finish(checksum, size, limits=limits)


def compressed_sizes(sources, *, format_version=FORMAT_VERSION):
    """Map archive paths to measured payload sizes without changing inventories."""
    return {artifact_path(source.root, source.key, format_version=format_version): source.compression.compressed_bytes
            for source in sources if source.compression is not None}


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


def artifact_path(root, key, *, format_version=FORMAT_VERSION):
    """Keep restoration identities independent of the human-readable layout."""
    root, key = _root(root), validate_key(key)
    if format_version == FORMAT_VERSION:
        return "artifacts/" + root + "/" + key
    if format_version != NATIVE_FORMAT_VERSION:
        raise TransferArchiveError("This package format version is unsupported.")
    if root == "database":
        if key == "metadata/deployment.json":
            return "configuration/deployment.json"
        if key.startswith("credentials/"):
            return "configuration/" + key
        return "database/" + key
    from .recovery_files import archive_path
    return validate_key(archive_path(root, key))


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


def _hash(stream, limit, output=None, *, report=None):
    digest, size = hashlib.sha256(), 0
    for block in iter(lambda: stream.read(BLOCK_SIZE), b""):
        size += len(block)
        if size > limit:
            raise TransferArchiveError("A package member exceeds its size limit.")
        digest.update(block)
        if output is not None:
            output.write(block)
        if report is not None:
            report(size)
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


def _entries(artifacts, limits, expected_artifacts, *, format_version=FORMAT_VERSION, report=None):
    sources, entries = list(artifacts), []
    expected = None if expected_artifacts is None else tuple(expected_artifacts)
    changed = "The files changed after review. Review the export again."
    if expected is not None and len(expected) != len(sources):
        raise TransferArchiveError(changed)
    hashed_bytes = 0
    for index, source in enumerate(sources):
        root, key = _root(source.root), validate_key(source.key)
        if expected is None:
            def progress(size):
                if report is not None:
                    report("hash_files", processed_bytes=hashed_bytes + size,
                           processed_items=index, total_items=len(sources))

            with open_regular(source.path, storage_root=source.storage_root) as stream:
                checksum, size, compression = hash_with_compression(
                    stream, limits.max_member_bytes, limits=limits,
                    report=progress if report is not None else None)
            source = sources[index] = replace(source, compression=compression)
            hashed_bytes += size
            if report is not None:
                report("hash_files", processed_bytes=hashed_bytes,
                       processed_items=index + 1, total_items=len(sources))
        else:
            reviewed = expected[index]
            if (not isinstance(reviewed, dict) or set(reviewed) != {"root", "key", "sha256", "size"}
                    or (reviewed["root"], reviewed["key"]) != (root, key)):
                raise TransferArchiveError(changed)
            checksum, size = reviewed["sha256"], reviewed["size"]
            _validate_descriptor({"path": artifact_path(root, key, format_version=format_version), "sha256": checksum, "size": size})
            with open_regular(source.path, storage_root=source.storage_root) as stream:
                if os.fstat(stream.fileno()).st_size != size:
                    raise TransferArchiveError(changed)
            # The reviewed digest is verified while copying below. Reading the
            # same large source a second time here adds no publication safety.
        if source.compression is not None:
            plan = source.compression
            if (not isinstance(plan, CompressionPlan) or (plan.sha256, plan.size) != (checksum, size)
                    or size > max(1, plan.compressed_bytes) * limits.max_compression_ratio):
                raise TransferArchiveError("The file compression plan does not match its reviewed bytes or resource limits.")
        entries.append({"root": root, "key": key,
                        **_descriptor(artifact_path(root, key, format_version=format_version), checksum, size)})
    return sources, entries


def _inventory_entries(entries, directories, *, format_version=FORMAT_VERSION):
    normalized = []
    for entry in entries:
        root, key = _root(entry["root"]), validate_key(entry["key"])
        item = {**entry, "path": artifact_path(root, key, format_version=format_version)}
        _validate_descriptor(item)
        normalized.append(item)
    directory_entries = [{"root": _root(item["root"]), "key": validate_key(item["key"])}
                         for item in directories]
    _validate_names(["manifest.json", "records.json", *(entry["path"] for entry in normalized)])
    file_names = {entry["path"].casefold() for entry in normalized}
    directory_names = [artifact_path(item["root"], item["key"], format_version=format_version) for item in directory_entries]
    if len({name.casefold() for name in directory_names}) != len(directory_names):
        raise TransferArchiveError("Directory inventory entries collide.")
    for name in directory_names:
        parts = PurePosixPath(name.casefold()).parts
        if any("/".join(parts[:index]) in file_names for index in range(1, len(parts) + 1)):
            raise TransferArchiveError("File and directory inventory paths collide.")
    return normalized, directory_entries


def _package_metadata(manifest, records, entries, directories, storage, limits, *, validate_limits=True,
                      format_version=FORMAT_VERSION):
    if not isinstance(manifest, dict) or "archive" in manifest or not isinstance(records, (list, dict)):
        raise TransferArchiveError("The application package metadata is invalid.")
    if storage is not None and not isinstance(storage, dict):
        raise TransferArchiveError("The artifact storage metadata is invalid.")
    records_bytes = canonical_json(records)
    if validate_limits and len(records_bytes) > min(limits.max_records_bytes, limits.max_member_bytes):
        raise TransferArchiveError("The record payload exceeds its size limit.")
    entries, directories = _inventory_entries(entries, directories, format_version=format_version)
    if validate_limits and len(entries) + 2 > limits.max_members:
        raise TransferArchiveError("The package contains too many members.")
    if validate_limits and any(entry["size"] > limits.max_member_bytes for entry in entries):
        raise TransferArchiveError("A package member exceeds its size limit.")
    envelope = {**manifest, "archive": {
        "format": FORMAT, "version": format_version,
        "records": _descriptor("records.json", hashlib.sha256(records_bytes).hexdigest(), len(records_bytes)),
        "artifacts": entries, "directories": directories, "storage": storage or {},
    }}
    manifest_bytes = canonical_json(envelope)
    if validate_limits and len(manifest_bytes) > min(limits.max_manifest_bytes, limits.max_member_bytes):
        raise TransferArchiveError("The archive inventory exceeds its size limit.")
    if validate_limits and sum(item["size"] for item in entries) + len(records_bytes) + len(manifest_bytes) > limits.max_total_bytes:
        raise TransferArchiveError("The package exceeds its total size limit.")
    return records_bytes, manifest_bytes, entries, directories


def _zip_size(members):
    """Exact seekable ZIP layout with forced ZIP64 local headers.

    Each member supplies its name, original size and final compressed size.
    Central ZIP64 records depend on both sizes and the compressed file offset.
    """
    offset, central = 0, 0
    for name, size, compressed in members:
        length = len(name.encode("utf-8"))
        extra_values = (2 if max(size, compressed) > zipfile.ZIP64_LIMIT else 0) + (1 if offset > zipfile.ZIP64_LIMIT else 0)
        central += 46 + length + (4 + 8 * extra_values if extra_values else 0)
        offset += 30 + length + 20 + compressed
    zip64_end = (len(members) > zipfile.ZIP_FILECOUNT_LIMIT or offset > zipfile.ZIP64_LIMIT
                 or central > zipfile.ZIP64_LIMIT)
    return offset + central + 22 + (76 if zip64_end else 0), central


def estimate_archive_size(manifest, records, entries=(), *, directories=(), storage=None,
                          limits=None, artifacts_first=False, validate_limits=True,
                          format_version=FORMAT_VERSION, compressed_sizes=None):
    """Return the package's complete size, refusing unreadable output.

    Entries need root, key, sha256 and size; payload bytes are never read here.
    Optional measured compressed sizes use archive paths as keys. Members with
    no measurement are conservatively sized as stored original bytes.
    The native writer puts streamed artifacts before metadata.
    """
    limits = limits or ArchiveLimits()
    records_bytes, manifest_bytes, entries, _directories = _package_metadata(
        manifest, records, entries, directories, storage, limits, validate_limits=validate_limits,
        format_version=format_version)
    compressed_sizes = {} if compressed_sizes is None else compressed_sizes
    if not isinstance(compressed_sizes, dict) or any(
            not isinstance(name, str) or type(size) is not int or size < 0
            for name, size in compressed_sizes.items()):
        raise TransferArchiveError("The compressed package size measurements are invalid.")
    metadata = [("manifest.json", len(manifest_bytes), len(manifest_bytes)),
                ("records.json", len(records_bytes), len(records_bytes))]
    artifacts = [(entry["path"], entry["size"], compressed_sizes.get(entry["path"], entry["size"]))
                 for entry in entries]
    if validate_limits and any(size > max(1, compressed) * limits.max_compression_ratio
                               for _name, size, compressed in artifacts):
        raise TransferArchiveError("An archive member exceeds its resource limit.")
    members = artifacts + metadata if artifacts_first else metadata + artifacts
    archive_bytes, central_bytes = _zip_size(members)
    if validate_limits and central_bytes > limits.max_central_directory_bytes:
        raise TransferArchiveError("The archive contains too much ZIP metadata.")
    if validate_limits and archive_bytes > limits.max_archive_bytes:
        raise TransferArchiveError("The archive exceeds its size limit.")
    return {"archive_bytes": archive_bytes, "records_bytes": len(records_bytes),
            "manifest_bytes": len(manifest_bytes), "expanded_bytes": sum(size for _name, size, _compressed in members),
            "central_directory_bytes": central_bytes}


class _BoundedOutput:
    """Enforce package growth and its live filesystem reserve before every write."""

    def __init__(self, output, limits, check_space):
        self.output, self.limit, self.check_space = output, limits.max_archive_bytes, check_space
        self.size = 0

    def write(self, block):
        end = self.output.tell() + len(block)
        if end > self.limit:
            raise TransferArchiveError("The archive exceeds its size limit.")
        growth = max(0, end - self.size)
        if growth and self.check_space is not None:
            self.check_space(growth)
        written = self.output.write(block)
        if written != len(block):
            raise TransferArchiveError("The package could not be written completely.")
        self.size = max(self.size, self.output.tell())
        return written

    def tell(self):
        return self.output.tell()

    def seek(self, *args):
        return self.output.seek(*args)

    def flush(self):
        return self.output.flush()


class _DigestOutput:
    """A bounded stream accepted by capture callbacks without a fake fileno."""

    def __init__(self, output, limit):
        self.output, self.limit = output, limit
        self.digest, self.size = hashlib.sha256(), 0

    def write(self, block):
        if self.size + len(block) > self.limit:
            raise TransferArchiveError("A package member exceeds its size limit.")
        written = self.output.write(block)
        if written != len(block):
            raise TransferArchiveError("A package member could not be written completely.")
        self.digest.update(block)
        self.size += written
        return written


def _member(package, name, compression=None):
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    # Native custom dumps already contain compression. Metadata stays stored so
    # its complete header and inventory size can be calculated without rereads.
    info.compress_type = compression.compress_type if compression else zipfile.ZIP_STORED
    if compression is not None:
        # ZipFile.open has no compresslevel argument on supported Python 3.10+.
        info._compresslevel = compression.compresslevel
    return package.open(info, "w", force_zip64=True)


def _write_artifacts(package, sources, entries, limits, report=None):
    copied_bytes, total_bytes = 0, sum(entry["size"] for entry in entries)
    if report is not None:
        report("copy_files", processed_bytes=0, total_bytes=total_bytes,
               processed_items=0, total_items=len(entries))
    for index, (source, entry) in enumerate(zip(sources, entries)):
        def progress(size):
            if report is not None:
                report("copy_files", processed_bytes=copied_bytes + size, total_bytes=total_bytes,
                       processed_items=index, total_items=len(entries))

        with open_regular(source.path, storage_root=source.storage_root) as stream, _member(package, entry["path"], source.compression) as member:
            actual = _hash(stream, limits.max_member_bytes, member, report=progress if report is not None else None)
        if actual != (entry["sha256"], entry["size"]):
            raise TransferArchiveError("The files changed after review or while the package was being created.")
        info = package.getinfo(entry["path"])
        if source.compression is not None and info.compress_size != source.compression.compressed_bytes:
            raise TransferArchiveError("The compressed file size changed while the package was being created.")
        copied_bytes += actual[1]
        if report is not None:
            report("copy_files", processed_bytes=copied_bytes, total_bytes=total_bytes,
                   processed_items=index + 1, total_items=len(entries))


def _publish_archive(path, build, limits, check_space, report=None):
    path, temporary = Path(path), None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".transfer-", suffix=".pending",
                                         buffering=0, delete=False) as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            bounded = _BoundedOutput(output, limits, check_space)
            with zipfile.ZipFile(bounded, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as package:
                build(package)
                _validate_zip_members(package.infolist(), limits)
            output.flush()
            os.fsync(output.fileno())
            _check_central_directory(output, bounded.size, limits)
            if report is not None:
                report("verify_package", processed_bytes=0, total_bytes=bounded.size)

            def progress(size):
                report("verify_package", processed_bytes=size, total_bytes=bounded.size)

            checksum, _size = _hash(output, limits.max_archive_bytes, report=progress if report is not None else None)
        # Reopen the completed private ZIP through the import reader before it
        # becomes downloadable. This verifies CRCs, decompression, the complete
        # inventory and every original-byte digest with the same bounded rules.
        verified = inspect_archive(temporary, limits=limits)
        if verified.package_sha256 != checksum:
            raise TransferArchiveError("The completed package changed during integrity verification.")
        os.link(temporary, path)
        _sync_directory(path.parent)
        return checksum
    except OSError as exc:
        raise TransferArchiveError("The package could not be published without overwriting existing data.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_archive(path, manifest, records, artifacts=(), *, directories=(), storage=None, limits=None,
                  expected_artifacts=None, check_space=None, report=None):
    """Create a private, fsynced package without replacing an existing file."""
    limits = limits or ArchiveLimits()
    sources, entries = _entries(artifacts, limits, expected_artifacts, report=report)
    records_bytes, manifest_bytes, entries, _directories = _package_metadata(
        manifest, records, entries, directories, storage, limits)
    estimate_archive_size(manifest, records, entries, directories=_directories, storage=storage, limits=limits,
                          compressed_sizes=compressed_sizes(sources))

    def build(package):
        for name, payload in (("manifest.json", manifest_bytes), ("records.json", records_bytes)):
            with _member(package, name) as member:
                member.write(payload)
        _write_artifacts(package, sources, entries, limits, report)

    return _publish_archive(path, build, limits, check_space, report)


def write_native_archive(path, manifest, capture, artifacts=(), *, directories=(), storage=None,
                         limits=None, expected_artifacts=None, check_space=None, report=None):
    """Capture a PostgreSQL dump directly into its final package member.

    capture(stream) returns native metadata, including dump_sha256/dump_bytes,
    and optionally bounded supplementary bytes in its private _package_sections
    mapping. Supplemental metadata never duplicates the database data dump.
    Readers retain support for the original flat package layout.
    """
    limits = limits or ArchiveLimits()
    sources, entries = _entries(artifacts, limits, expected_artifacts,
                                format_version=NATIVE_FORMAT_VERSION, report=report)
    directory_entries = tuple(directories)
    native_key = "data/database.dump"
    native_name = artifact_path("database", native_key, format_version=NATIVE_FORMAT_VERSION)
    _validate_names([native_name, "manifest.json", "records.json", *(entry["path"] for entry in entries)])
    if len(entries) + 3 > limits.max_members:
        raise TransferArchiveError("The package contains too many members.")

    def build(package):
        with _member(package, native_name) as member:
            stream = _DigestOutput(member, min(limits.max_member_bytes,
                max(0, limits.max_total_bytes - sum(entry["size"] for entry in entries))))
            records = capture(stream)
        if not isinstance(records, dict) or (records.get("dump_sha256"), records.get("dump_bytes")) != (
                stream.digest.hexdigest(), stream.size):
            raise TransferArchiveError("The captured PostgreSQL dump failed integrity verification.")
        records = dict(records)
        sections = records.pop("_package_sections", {})
        if not isinstance(sections, dict) or any(not isinstance(payload, bytes) for payload in sections.values()):
            raise TransferArchiveError("The PostgreSQL supplemental metadata is invalid.")
        native = {"root": "database", "key": native_key,
                  **_descriptor(native_name, stream.digest.hexdigest(), stream.size)}
        supplemental = [{"root": "database", "key": validate_key(key),
                         **_descriptor(artifact_path("database", key, format_version=NATIVE_FORMAT_VERSION),
                                       hashlib.sha256(payload).hexdigest(), len(payload))}
                        for key, payload in sections.items()]
        if sections:
            records["sections"] = [{name: item[name] for name in ("key", "sha256", "size")}
                                   for item in supplemental]
        all_entries = [native, *supplemental, *entries]
        records_bytes, manifest_bytes, all_entries, normalized_dirs = _package_metadata(
            manifest, records, all_entries, directory_entries, storage, limits,
            format_version=NATIVE_FORMAT_VERSION)
        estimate_archive_size(manifest, records, all_entries, directories=normalized_dirs,
                              storage=storage, limits=limits, artifacts_first=True,
                              format_version=NATIVE_FORMAT_VERSION,
                              compressed_sizes=compressed_sizes(sources, format_version=NATIVE_FORMAT_VERSION))
        for entry in supplemental:
            with _member(package, entry["path"]) as member:
                payload = memoryview(sections[entry["key"]])
                for offset in range(0, len(payload), BLOCK_SIZE):
                    member.write(payload[offset:offset + BLOCK_SIZE])
        _write_artifacts(package, sources, entries, limits, report)
        for name, payload in (("manifest.json", manifest_bytes), ("records.json", records_bytes)):
            with _member(package, name) as member:
                member.write(payload)

    return _publish_archive(path, build, limits, check_space, report)


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


def _validate_zip_members(infos, limits):
    """Apply the same bounded member rules to written and received packages."""
    _validate_names([item.filename for item in infos])
    if len(infos) > limits.max_members:
        raise TransferArchiveError("The archive contains too many members.")
    total = 0
    for item in infos:
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (item.is_dir() or kind not in (0, stat.S_IFREG) or item.flag_bits & 1
                or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise TransferArchiveError("Only unencrypted regular data files are supported.")
        if (item.file_size > limits.max_member_bytes
                or item.file_size > max(1, item.compress_size) * limits.max_compression_ratio):
            raise TransferArchiveError("An archive member exceeds its resource limit.")
        total += item.file_size
    if total > limits.max_total_bytes:
        raise TransferArchiveError("The archive exceeds its total size limit.")


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
                _validate_zip_members(infos, limits)
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
                if not isinstance(envelope, dict) or set(envelope) != {"format", "version", "records", "artifacts", "directories", "storage"} or envelope.get("format") != FORMAT or type(envelope.get("version")) is not int or envelope["version"] not in (FORMAT_VERSION, NATIVE_FORMAT_VERSION):
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
                    if set(entry) != {"root", "key", "path", "size", "sha256"} or entry["path"] != artifact_path(entry["root"], entry["key"], format_version=envelope["version"]):
                        raise TransferArchiveError("An artifact destination is invalid.")
                directory_names = []
                for entry in directories:
                    if not isinstance(entry, dict) or set(entry) != {"root", "key"}:
                        raise TransferArchiveError("A directory inventory entry is invalid.")
                    directory_names.append(artifact_path(entry["root"], entry["key"], format_version=envelope["version"]))
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
    except (OSError, ValueError, EOFError, struct.error, zipfile.BadZipFile, zlib.error,
            RuntimeError, NotImplementedError) as exc:
        raise TransferArchiveError("The package is damaged or uses an unsupported ZIP encoding.") from exc
