"""Explicit, bounded deployment recovery evidence; never applied as settings.

Only application-owned credentials and allowlisted runtime settings enter this
section. Plaintext secrets stay inside the private backup payload, never its
operation journal, preview, exception or log.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import base64
import binascii
import hashlib
import os
from pathlib import Path
import re
import stat

from django.conf import settings
from django.db import connection

from qc_tool.common import CONFIG, WORKER_TOKEN_FILENAME
from qc_tool.database import selection as database_selection
from qc_tool.product_security import canonical_product_ident
from .archive import canonical_json, open_regular, _json
from .contracts import digest
from .errors import TransferError


FORMAT = "qc-tool-deployment-configuration"
MAX_BYTES = 32 * 1024**2
MAX_FILES = 10_000
MAX_ACTIVATION_FILE_BYTES = 1024**2
_BOUNDARY_LINKS = (".boundary-current", "raster", "vector")
_GENERATION_TARGET = re.compile(r"\.boundary-generations/(?:gen|legacy)-[a-f0-9]{32}\Z")
_CREDENTIAL = re.compile(r"[a-f0-9]{32}\.json\Z")
_KEY = re.compile(r"credentials/s3/[a-f0-9]{32}\.json\Z")
_AUXILIARY = re.compile(r"credentials/(?:worker\.token|postgresql/(?:sslcert|sslkey|sslrootcert|sslcrl))\Z")
_SETTINGS = ("SECRET_KEY", "SECRET_KEY_FALLBACKS", "TIME_ZONE", "USE_TZ", "ALLOWED_HOSTS",
             "CSRF_TRUSTED_ORIGINS", "S3_ALLOWED_ENDPOINTS", "S3_CREDENTIALS_DIR")
_DATABASE = ("ENGINE", "NAME", "USER", "PASSWORD", "HOST", "PORT", "OPTIONS")
_STORAGE = ("work_dir", "incoming_dir", "boundary_dir", "product_dirs", "submission_dir")


@dataclass(frozen=True)
class ConfigurationSnapshot:
    sections: dict = field(repr=False)
    fingerprint: str
    files_count: int
    byte_count: int


def _value(value):
    if value is None or type(value) in {str, bool, int, float}:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_value(item) for item in value]
        return sorted(items) if isinstance(value, (set, frozenset)) else items
    raise TransferError("A deployment setting cannot be captured as portable recovery metadata.")


def _identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@contextmanager
def _activation_directory(root, *parts):
    """Open only real configured directories; keep every ancestor under review."""
    opened = []
    try:
        try:
            current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            opened.append((current, _identity(os.fstat(current)), None, root))
            for part in parts:
                parent = current
                current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                opened.append((current, _identity(os.fstat(current)), parent, part))
        except FileNotFoundError:
            current = None
        yield current
        for descriptor, before, parent, name in opened:
            if (_identity(os.fstat(descriptor)) != before
                    or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != before):
                raise TransferError("Application activation metadata changed during backup. Review it again.")
    finally:
        for descriptor, _before, _parent, _name in reversed(opened):
            os.close(descriptor)


def _valid_boundary_target(name, target):
    return (bool(_GENERATION_TARGET.fullmatch(target)) if name == ".boundary-current"
            else target == ".boundary-current/" + name)


def _activation_snapshot():
    """Preserve activation evidence as inert data without resolving any link."""
    boundary = {"state": "absent", "entries": {}}
    with _activation_directory(Path(CONFIG["boundary_dir"])) as descriptor:
        if descriptor is not None:
            boundary["state"] = "included"
            for name in _BOUNDARY_LINKS:
                try:
                    before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    boundary["entries"][name] = {"state": "absent"}
                    continue
                if stat.S_ISLNK(before.st_mode):
                    target = os.readlink(name, dir_fd=descriptor)
                    if not _valid_boundary_target(name, target):
                        raise TransferError("A boundary activation link has an unsupported or unsafe target.")
                    boundary["entries"][name] = {"state": "link", "target": target}
                elif name != ".boundary-current" and stat.S_ISDIR(before.st_mode):
                    boundary["entries"][name] = {"state": "directory"}
                else:
                    raise TransferError("Boundary activation metadata contains an unsupported object.")
                if _identity(os.stat(name, dir_fd=descriptor, follow_symlinks=False)) != _identity(before):
                    raise TransferError("Boundary activation metadata changed during backup. Review it again.")
                if stat.S_ISLNK(before.st_mode) and os.readlink(name, dir_fd=descriptor) != target:
                    raise TransferError("Boundary activation metadata changed during backup. Review it again.")
    specifications = {"state": "absent", "files": []}
    total = 0
    with _activation_directory(Path(CONFIG["work_dir"]), "product_definitions", ".state") as descriptor:
        if descriptor is not None:
            specifications["state"] = "included"
            names = os.listdir(descriptor)
            if len(names) > MAX_FILES:
                raise TransferError("Specification activation metadata exceeds its supported file limit.")
            for name in sorted(names):
                metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    raise TransferError("Specification activation metadata must contain original regular files.")
                if name.startswith(".state-"):
                    continue
                if not name.endswith(".json") or canonical_product_ident(name[:-5]) is None:
                    raise TransferError("Specification activation metadata contains an unsupported filename.")
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                with os.fdopen(handle, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(metadata):
                        raise TransferError("Specification activation metadata changed during backup. Review it again.")
                    raw = stream.read(MAX_ACTIVATION_FILE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                if len(raw) > MAX_ACTIVATION_FILE_BYTES or _identity(before) != _identity(after):
                    raise TransferError("Specification activation metadata changed or exceeded its supported size.")
                encoded = base64.b64encode(raw).decode("ascii")
                total += len(encoded)
                if total > MAX_BYTES:
                    raise TransferError("Specification activation metadata exceeds its package metadata limit.")
                specifications["files"].append({"key": name, "sha256": hashlib.sha256(raw).hexdigest(),
                                                "size": len(raw), "content_base64": encoded})
    return {"boundaries": boundary, "specifications": specifications}


def _validate_activation(activation):
    if not isinstance(activation, dict) or set(activation) != {"boundaries", "specifications"}:
        raise TransferError("The deployment activation metadata is unsupported.")
    boundary = activation["boundaries"]
    if (not isinstance(boundary, dict) or set(boundary) != {"state", "entries"}
            or not isinstance(boundary["state"], str) or boundary["state"] not in {"included", "absent"}
            or not isinstance(boundary["entries"], dict)
            or set(boundary["entries"]) != (set(_BOUNDARY_LINKS) if boundary["state"] == "included" else set())):
        raise TransferError("The boundary activation metadata is unsupported.")
    for name, entry in boundary["entries"].items():
        if entry == {"state": "absent"} or (name != ".boundary-current" and entry == {"state": "directory"}):
            continue
        if (not isinstance(entry, dict) or set(entry) != {"state", "target"} or entry["state"] != "link"
                or not isinstance(entry["target"], str) or not _valid_boundary_target(name, entry["target"])):
            raise TransferError("The boundary activation link target is unsupported or unsafe.")
    specifications = activation["specifications"]
    if (not isinstance(specifications, dict) or set(specifications) != {"state", "files"}
            or not isinstance(specifications["state"], str) or specifications["state"] not in {"included", "absent"}
            or not isinstance(specifications["files"], list)
            or len(specifications["files"]) > MAX_FILES
            or (specifications["state"] == "absent" and specifications["files"])):
        raise TransferError("The specification activation metadata is unsupported.")
    seen = set()
    for entry in specifications["files"]:
        if (not isinstance(entry, dict) or set(entry) != {"key", "sha256", "size", "content_base64"}
                or not isinstance(entry["key"], str) or not entry["key"].endswith(".json")
                or canonical_product_ident(entry["key"][:-5]) is None or entry["key"] in seen
                or type(entry["size"]) is not int or not 0 <= entry["size"] <= MAX_ACTIVATION_FILE_BYTES
                or not isinstance(entry["content_base64"], str)
                or len(entry["content_base64"]) > 4 * ((MAX_ACTIVATION_FILE_BYTES + 2) // 3)):
            raise TransferError("The specification activation file inventory is invalid.")
        seen.add(entry["key"])
        try:
            raw = base64.b64decode(entry["content_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise TransferError("The specification activation bytes are invalid.") from None
        if (len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]
                or base64.b64encode(raw).decode("ascii") != entry["content_base64"]):
            raise TransferError("The specification activation bytes disagree with their inventory.")


def snapshot():
    sections, credentials = {}, []
    root = Path(settings.S3_CREDENTIALS_DIR)
    total = 0
    try:
        try:
            metadata = root.lstat()
        except FileNotFoundError:
            metadata = None
        if metadata is not None:
            if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o077
                    or metadata.st_uid != os.geteuid()):
                raise TransferError("The selected application credential store must be a private owned directory.")
            with os.scandir(root) as files:
                names = []
                for item in files:
                    if len(names) >= MAX_FILES:
                        raise TransferError("The application credential inventory exceeds its supported file limit.")
                    names.append(item.name)
                names.sort()
            for name in names:
                # Incomplete atomic writes are runtime scratch, never credentials.
                if name.startswith(".") and name.endswith(".tmp"):
                    continue
                if not _CREDENTIAL.fullmatch(name):
                    raise TransferError("The application credential store contains an unsupported entry. Inspect it before exporting configuration.")
                with open_regular(root / name, storage_root=root) as stream:
                    before = os.fstat(stream.fileno())
                    if before.st_mode & 0o077 or before.st_nlink != 1 or before.st_uid != os.geteuid():
                        raise TransferError("An application credential file is not private and exclusively owned.")
                    raw = stream.read(8193)
                    after = os.fstat(stream.fileno())
                identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
                if len(raw) > 8192 or identity(before) != identity(after):
                    raise TransferError("An application credential file changed or exceeded its supported size.")
                total += len(raw)
                if total > MAX_BYTES:
                    raise TransferError("The selected deployment configuration exceeds its package metadata limit.")
                key = "credentials/s3/" + name
                sections[key] = raw
                credentials.append({"key": key, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        database = {name: _value(connection.settings_dict.get(name)) for name in _DATABASE}
        database["NAME"] = str(database_selection.current_database())
        auxiliary = []
        candidates = [("credentials/worker.token", Path(CONFIG["work_dir"]) / WORKER_TOKEN_FILENAME, True, False)]
        options = connection.settings_dict.get("OPTIONS") or {}
        for name in ("sslcert", "sslkey", "sslrootcert", "sslcrl"):
            if options.get(name):
                candidates.append(("credentials/postgresql/" + name, Path(options[name]), name == "sslkey", True))
        for key, path, private, required in candidates:
            if not os.path.lexists(path) and not required:
                continue
            with open_regular(path) as stream:
                before = os.fstat(stream.fileno())
                if private and (before.st_mode & 0o077 or before.st_nlink != 1 or before.st_uid != os.geteuid()):
                    raise TransferError("A selected deployment secret file is not private and exclusively owned.")
                raw = stream.read(1024**2 + 1)
                after = os.fstat(stream.fileno())
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if len(raw) > 1024**2 or identity(before) != identity(after):
                raise TransferError("A selected deployment file changed or exceeded its supported size.")
            sections[key] = raw
            total += len(raw)
            auxiliary.append({"key": key, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        document = {"format": FORMAT, "version": 1,
                    "settings": {name: _value(getattr(settings, name, None)) for name in _SETTINGS},
                    "database": database,
                    "storage": {name: _value(CONFIG.get(name)) for name in _STORAGE},
                    "credential_store": {"state": "included" if metadata is not None else "absent", "files": credentials},
                    "auxiliary_files": auxiliary,
                    "activation": _activation_snapshot(),
                    "restore": "operator_review_only"}
        sections["metadata/deployment.json"] = canonical_json(document)
        total += len(sections["metadata/deployment.json"])
        if total > MAX_BYTES:
            raise TransferError("The selected deployment configuration exceeds its package metadata limit.")
    except OSError:
        raise TransferError("The selected application configuration or credential files could not be captured completely.") from None
    fingerprint = digest([{ "key": key, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
                          for key, raw in sorted(sections.items())])
    return ConfigurationSnapshot(sections, fingerprint, len(sections), total)


def validate(archive):
    """Verify declared recovery files without exposing or activating secrets."""
    entries = {entry["key"]: entry for entry in archive.entries if entry["root"] == "database"}
    entry = entries.get("metadata/deployment.json")
    credentials = {key: value for key, value in entries.items() if key.startswith("credentials/")}
    if entry is None:
        if credentials:
            raise TransferError("Credential files require deployment recovery metadata.")
        return
    if entry["size"] > MAX_BYTES:
        raise TransferError("Deployment recovery metadata exceeds its supported limit.")
    with archive.open_artifact(entry) as stream:
        document = _json(stream.read(MAX_BYTES + 1))
    if (not isinstance(document, dict)
            or set(document) != {"format", "version", "settings", "database", "storage", "credential_store", "auxiliary_files", "activation", "restore"}
            or document["format"] != FORMAT or type(document["version"]) is not int or document["version"] != 1
            or document["restore"] != "operator_review_only"
            or not isinstance(document["settings"], dict) or set(document["settings"]) != set(_SETTINGS)
            or not isinstance(document["database"], dict) or set(document["database"]) != set(_DATABASE)
            or not isinstance(document["storage"], dict) or set(document["storage"]) != set(_STORAGE)):
        raise TransferError("The deployment recovery metadata is unsupported.")
    _validate_activation(document["activation"])
    store = document["credential_store"]
    if (not isinstance(store, dict) or set(store) != {"state", "files"}
            or store["state"] not in {"included", "absent"} or not isinstance(store["files"], list)
            or (store["state"] == "absent" and store["files"])):
        raise TransferError("The deployment credential inventory is unsupported.")
    if not isinstance(document["auxiliary_files"], list) or len(document["auxiliary_files"]) > 5 or len(store["files"]) > MAX_FILES:
        raise TransferError("The deployment file inventory exceeds its supported limit.")
    declared = {}
    for item in store["files"]:
        if (not isinstance(item, dict) or set(item) != {"key", "sha256", "size"}
                or not isinstance(item["key"], str) or not _KEY.fullmatch(item["key"])
                or item["key"] in declared or type(item["size"]) is not int or not 0 <= item["size"] <= 8192):
            raise TransferError("The deployment credential inventory is invalid.")
        declared[item["key"]] = item
    for item in document["auxiliary_files"]:
        if (not isinstance(item, dict) or set(item) != {"key", "sha256", "size"}
                or not isinstance(item["key"], str) or not _AUXILIARY.fullmatch(item["key"])
                or item["key"] in declared or type(item["size"]) is not int or not 0 <= item["size"] <= 1024**2):
            raise TransferError("The deployment auxiliary file inventory is invalid.")
        declared[item["key"]] = item
    actual = {key: {name: value[name] for name in ("key", "sha256", "size")} for key, value in credentials.items()}
    if declared != actual or sum(item["size"] for item in [entry, *credentials.values()]) > MAX_BYTES:
        raise TransferError("The deployment credential files disagree with their recovery metadata.")
