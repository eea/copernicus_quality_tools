"""Explicit storage inventory and create-only restoration of transfer artifacts.

Only business-owned namespaces are supported. Runtime state, session/token
secrets, S3 credentials, scratch files and service logs never enter a package.
Filesystem changes are durable before the caller commits database records.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import UUID

from qc_tool.common import CONFIG, JOB_INPUT_DIRNAME, JOB_OUTPUT_DIRNAME, JOB_TMP_DIRNAME
from qc_tool.product_security import canonical_product_ident
from qc_tool.frontend.dashboard.services.boundaries.resolver import resolve_boundary_generation
from qc_tool.frontend.dashboard.services.boundaries.layout import validate_generation_id
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import parse_definition_snapshot
from qc_tool.frontend.dashboard.services.submissions.publication.integrity import _expected_inventory, verify_publication_inventory
from qc_tool.frontend.dashboard.services.submissions.publication.identity import verify_manifest_identity

from .archive import ArtifactSource, TransferArchiveError, _hash, _json, _sync_directory, canonical_json, open_regular, validate_key


_SHA = re.compile(r"^[0-9a-f]{64}$")


def without_payloads(archive):
    """Validate a package, then retain expected links without restoring bytes."""
    from .artifact_references import without_payloads as strip
    return strip(archive)


@dataclass(frozen=True)
class ArtifactInventory:
    sources: tuple = ()
    directories: tuple = ()
    storage: dict = field(default_factory=dict)
    warnings: tuple = ()
    external_requirements: tuple = ()


def storage_roots():
    result = {"work": Path(CONFIG["work_dir"]), "incoming": Path(CONFIG["incoming_dir"]),
              "boundaries": Path(CONFIG["boundary_dir"])}
    if CONFIG.get("submission_dir"):
        result["submissions"] = Path(CONFIG["submission_dir"])
    for index, directory in enumerate(CONFIG["product_dirs"]):
        result[f"product-{index}"] = Path(directory)
    return result


def _rows(payload, resource):
    return payload.get("records", {}).get(resource, [])


def _safe_directory(root, key="", *, required=True):
    root = Path(root)
    if key:
        validate_key(key)
    current = root
    for part in (None, *Path(key).parts):
        if part is not None:
            current /= part
        if current.is_symlink():
            raise TransferArchiveError("Artifact storage contains a symbolic link.")
        if not current.exists():
            if not required:
                return None
            raise TransferArchiveError("Required artifact storage is unavailable.")
        if not current.is_dir():
            raise TransferArchiveError("Artifact storage is not a directory.")
    return current


def _tree(root, key, sources, directories, *, root_name, filter_file=None):
    path = _safe_directory(root, key)
    directories.append({"root": root_name, "key": validate_key(key)})
    for entry in sorted(os.scandir(path), key=lambda item: item.name):
        relative = key + "/" + entry.name
        validate_key(relative)
        if entry.is_symlink():
            raise TransferArchiveError("An artifact tree contains a symbolic link.")
        if entry.is_dir(follow_symlinks=False):
            _tree(root, relative, sources, directories, root_name=root_name, filter_file=filter_file)
        elif entry.is_file(follow_symlinks=False):
            if filter_file is None or filter_file(relative):
                sources.append(ArtifactSource(root_name, relative, Path(entry.path), Path(root)))
        else:
            raise TransferArchiveError("An artifact tree contains a special filesystem object.")


def _digest_source(source):
    with open_regular(source.path, storage_root=source.storage_root) as stream:
        return _hash(stream, 16 * 1024**3)[0]


def _spec_path(key):
    parts = Path(key).parts
    if not parts or parts[0] != "product_definitions":
        return False
    if len(parts) == 2:
        return parts[1].endswith(".json") and canonical_product_ident(parts[1][:-5]) is not None
    if len(parts) == 3 and parts[1] == ".state":
        return parts[2].endswith(".json") and canonical_product_ident(parts[2][:-5]) is not None
    return len(parts) == 4 and parts[1] == ".versions" and canonical_product_ident(parts[2]) is not None and parts[3].endswith(".json") and bool(_SHA.fullmatch(parts[3][:-5]))


def _spec_ident(key):
    parts = Path(key).parts
    return parts[2] if len(parts) == 4 and parts[1] == ".versions" else parts[-1][:-5]


def _identifiers(payload):
    return {value for resource, field in (("products", "ident"), ("definitions", "product_ident"), ("jobs", "product_ident"))
            for row in _rows(payload, resource) if (value := row.get(field))}


def collect_artifacts(payload, *, roots=None, include_files=None):
    """Read the complete supported application inventory without mutating it."""

    if include_files is not None:
        if type(include_files) is not bool:
            raise TransferArchiveError("Choose whether to include file payloads.")
        from .artifact_references import collect_optional_artifacts
        return collect_optional_artifacts(payload, roots=roots or storage_roots(), include_files=include_files)
    if payload.get("profile") == "accounts":
        return ArtifactInventory()
    roots = roots or storage_roots()
    sources, directories, warnings, external = [], [], [], []
    identifiers = _identifiers(payload)
    accounts = {int(item["key"]): item["username"] for item in payload["accounts"]}
    for delivery in _rows(payload, "deliveries"):
        if delivery["s3_id"] is not None:
            external.append("Remote delivery {} requires separately provisioned S3 access; credentials and remote objects are excluded.".format(delivery["id"]))
            continue
        username = accounts.get(delivery["user_id"])
        if username is None:
            if not delivery["is_deleted"]:
                raise TransferArchiveError("A retained local delivery has no identifiable storage owner.")
            warnings.append("Deleted delivery {} has no retained upload owner.".format(delivery["id"]))
            continue
        key = validate_key(username + "/" + delivery["filename"])
        if Path(delivery["filename"]).name != delivery["filename"] or not delivery["filename"].lower().endswith(".zip"):
            raise TransferArchiveError("A retained delivery uses an unsupported upload filename.")
        source = ArtifactSource("incoming", key, roots["incoming"] / key, roots["incoming"])
        if not source.path.exists() and not source.path.is_symlink() and delivery["is_deleted"]:
            warnings.append("Deleted delivery {} has no retained ZIP.".format(delivery["id"]))
            continue
        with open_regular(source.path, storage_root=source.storage_root) as stream:
            digest, size = _hash(stream, 16 * 1024**3)
        if size != delivery["size_bytes"] or (delivery.get("content_sha256") and digest != delivery["content_sha256"]):
            raise TransferArchiveError("A retained delivery ZIP differs from its database record.")
        sources.append(source)
    for job in _rows(payload, "jobs"):
        key = "job_" + UUID(job["job_uuid"]).hex
        directory = _safe_directory(roots["work"], key, required=False)
        if directory is None:
            warnings.append("Job {} has no retained working artifacts; its database history remains available.".format(job["job_uuid"]))
            continue
        # Retain report/result/spec snapshots and attachments. Worker input and
        # scratch directories can contain secrets, temporary database exports or
        # downloaded remote objects and are deliberately outside this contract.
        directories.append({"root": "work", "key": key})
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            if entry.name == JOB_OUTPUT_DIRNAME:
                _tree(roots["work"], key + "/" + entry.name, sources, directories, root_name="work")
            elif entry.is_symlink():
                raise TransferArchiveError("A retained job artifact is a symbolic link.")
            elif entry.is_file(follow_symlinks=False):
                if entry.name.lower().endswith((".log", ".stdout", ".pre")):
                    continue
                sources.append(ArtifactSource("work", key + "/" + entry.name, Path(entry.path), roots["work"]))
            elif not entry.is_dir(follow_symlinks=False):
                raise TransferArchiveError("A retained job artifact is a special file.")
    for submission in _rows(payload, "submissions"):
        if submission["publication_state"] != "published":
            continue
        if "submissions" not in roots:
            raise TransferArchiveError("Published receipts require configured submission storage.")
        key = validate_key(submission["artifact_key"])
        directory = _safe_directory(roots["submissions"], key)
        with open_regular(directory / "submission-manifest.json", storage_root=roots["submissions"]) as stream:
            payload_bytes = stream.read(2 * 1024**2 + 1)
        if len(payload_bytes) > 2 * 1024**2:
            raise TransferArchiveError("A publication manifest exceeds its size limit.")
        manifest = _json(payload_bytes)
        _verify_receipt(manifest, submission, payload)
        try:
            verify_publication_inventory(directory, manifest, manifest_filename="submission-manifest.json", required_paths=("SUBMITTED",))
        except ValueError as exc:
            raise TransferArchiveError("Published artifacts failed their immutable inventory checks.") from exc
        _tree(roots["submissions"], key, sources, directories, root_name="submissions")
    # Configured specification directories are application configuration,
    # represented by stable positional roots, never arbitrary absolute paths.
    for name, root in roots.items():
        if not name.startswith("product-"):
            continue
        if _safe_directory(root, required=False) is None:
            raise TransferArchiveError("A configured specification directory is unavailable.")
        for entry in sorted(os.scandir(root), key=lambda item: item.name):
            if entry.name.endswith(".json") and entry.name[:-5] in identifiers:
                if not entry.is_file(follow_symlinks=False) or entry.is_symlink():
                    raise TransferArchiveError("Configured specifications must be regular files.")
                sources.append(ArtifactSource(name, validate_key(entry.name), Path(entry.path), root))
    uploaded = _safe_directory(roots["work"], "product_definitions", required=False)
    if uploaded is not None:
        _tree(roots["work"], "product_definitions", sources, directories, root_name="work",
              filter_file=lambda key: _spec_path(key) and _spec_ident(key) in identifiers)
        # Lock and staging files were excluded; directories outside the reviewed
        # namespace are not published to the destination either.
        directories = [item for item in directories if item["root"] != "work" or not item["key"].startswith("product_definitions/") or _spec_directory(item["key"])]
    digests = {_digest_source(item) for item in sources if item.key.endswith(".json") and (item.root.startswith("product-") or item.root == "work")}
    if any(definition["digest"] not in digests for definition in _rows(payload, "definitions")):
        raise TransferArchiveError("Original specification bytes are missing for a definition revision; a JSON database document cannot replace them.")
    boundary_state = {}
    root = roots["boundaries"]
    if _safe_directory(root, required=False) is None or not any(root.iterdir()):
        warnings.append("Boundary storage is empty or unavailable; provision required boundary packages before running QC.")
    else:
        try:
            generation = resolve_boundary_generation(root)
        except Exception as exc:
            raise TransferArchiveError("The active boundary generation cannot be resolved safely.") from exc
        if generation.managed:
            parent = _safe_directory(root, ".boundary-generations")
            for entry in sorted(os.scandir(parent), key=lambda item: item.name):
                try:
                    validate_generation_id(entry.name)
                except Exception as exc:
                    raise TransferArchiveError("Boundary storage contains an unsupported generation.") from exc
                _tree(root, ".boundary-generations/" + entry.name, sources, directories, root_name="boundaries")
            boundary_state = {"mode": "managed", "generation": generation.generation_id}
        else:
            for name in ("raster", "vector"):
                _tree(root, name, sources, directories, root_name="boundaries")
            boundary_state = {"mode": "legacy"}
    unique = {}
    for item in sources:
        previous = unique.setdefault((item.root, item.key), item)
        if previous.path != item.path:
            raise TransferArchiveError("The artifact inventory contains conflicting source paths.")
    unique_directories = {(item["root"], item["key"]): item for item in directories}
    return ArtifactInventory(tuple(unique[key] for key in sorted(unique)), tuple(unique_directories[key] for key in sorted(unique_directories)),
                             {"boundaries": boundary_state}, tuple(warnings), tuple(external))


def _spec_directory(key):
    parts = Path(key).parts
    return key in {"product_definitions", "product_definitions/.versions", "product_definitions/.state"} or (len(parts) == 3 and parts[1] == ".versions" and canonical_product_ident(parts[2]) is not None)


def _verify_receipt(manifest, submission, payload=None):
    from .provenance import get_package_publication_identity

    identity = dict(submission)
    if payload is not None:
        identity.update(get_package_publication_identity(payload, submission) or {})
    try:
        verify_manifest_identity(manifest, identity)
    except (ValueError, TypeError) as exc:
        raise TransferArchiveError(str(exc)) from exc


def _allowed_paths(archive):
    """Bind destination namespaces to the already validated business records."""

    payload = archive.records
    accounts = {int(item["key"]): item["username"] for item in payload.get("accounts", [])}
    uploads = {accounts.get(row["user_id"], "") + "/" + row["filename"] for row in _rows(payload, "deliveries") if row["s3_id"] is None}
    jobs = {"job_" + UUID(row["job_uuid"]).hex for row in _rows(payload, "jobs")}
    submissions = {row["artifact_key"] for row in _rows(payload, "submissions") if row["publication_state"] == "published"}
    identifiers = _identifiers(payload)

    def allowed(root, key, directory=False):
        parts = Path(key).parts
        if root == "incoming":
            return key in uploads if not directory else any(item.startswith(key + "/") for item in uploads)
        if root == "work":
            if parts[0] == "product_definitions":
                return _spec_directory(key) if directory else _spec_path(key) and _spec_ident(key) in identifiers
            if parts[0] not in jobs:
                return False
            if directory:
                return len(parts) == 1 or parts[1] == JOB_OUTPUT_DIRNAME
            return (len(parts) == 2 and not parts[1].lower().endswith((".log", ".stdout", ".pre"))) or (len(parts) > 2 and parts[1] == JOB_OUTPUT_DIRNAME)
        if root == "submissions":
            return any(key == item or key.startswith(item + "/") for item in submissions)
        if root == "boundaries":
            state = archive.storage.get("boundaries", {})
            if state.get("mode") == "legacy":
                return parts[0] in {"raster", "vector"}
            if state.get("mode") in {"managed", "retained"} and len(parts) >= 2 and parts[0] == ".boundary-generations":
                try:
                    validate_generation_id(parts[1])
                    return True
                except Exception:
                    return False
            return False
        return bool(re.fullmatch(r"product-[0-9]+", root)) and not directory and len(parts) == 1 and key.endswith(".json") and key[:-5] in identifiers

    return allowed


def _validate_package_artifacts(archive):
    if archive.records.get("profile") == "accounts":
        if archive.entries or archive.directories or set(archive.storage) - {"compatibility"}:
            raise TransferArchiveError("Account packages cannot contain storage artifacts.")
        return
    optional = "references" in archive.storage
    if set(archive.storage) - {"compatibility"} != ({"boundaries", "references"} if optional else {"boundaries"}) or not isinstance(archive.storage.get("boundaries"), dict):
        raise TransferArchiveError("The application storage contract is invalid.")
    boundary = archive.storage["boundaries"]
    if boundary:
        if boundary == {"mode": "legacy"}:
            pass
        elif optional and boundary == {"mode": "retained"}:
            pass
        elif set(boundary) == {"mode", "generation"} and boundary["mode"] == "managed":
            try:
                validate_generation_id(boundary["generation"])
            except Exception as exc:
                raise TransferArchiveError("The active boundary generation is invalid.") from exc
        else:
            raise TransferArchiveError("The boundary activation contract is invalid.")
    allowed = _allowed_paths(archive)
    for directory, items in ((False, archive.entries), (True, archive.directories)):
        for entry in items:
            if not allowed(entry["root"], entry["key"], directory):
                raise TransferArchiveError("The package attempts to write outside a supported business namespace.")
    files = {(item["root"], item["key"]): item for item in archive.entries}
    dirs = {(item["root"], item["key"]) for item in archive.directories}
    for root, key in dirs:
        if (root, key) in files or any((root, "/".join(Path(key).parts[:index])) in files for index in range(1, len(Path(key).parts))):
            raise TransferArchiveError("The package contains conflicting file and directory destinations.")
    if optional:
        from .artifact_references import validate_reference_inventory
        validate_reference_inventory(archive)
    reference_index = {(ref["resource"], ref["source_key"], ref["role"], ref["root"], ref["key"]): ref
                       for ref in archive.storage.get("references", {}).get("items", ())}
    for entry in archive.entries:
        parts = Path(entry["key"]).parts
        is_product = entry["root"].startswith("product-")
        is_uploaded = entry["root"] == "work" and parts[0] == "product_definitions"
        if not is_product and not is_uploaded:
            continue
        if entry["size"] > 1024**2:
            raise TransferArchiveError("Specification storage contains an oversized document.")
        with archive.open_artifact(entry) as stream:
            original = stream.read(1024**2 + 1)
        if is_uploaded and len(parts) == 3 and parts[1] == ".state":
            state = _json(original)
            if not isinstance(state, dict) or type(state.get("active")) is not bool or set(state) - {"active", "digest"}:
                raise TransferArchiveError("A specification activation marker is invalid.")
            if state["active"]:
                digest = state.get("digest")
                if not isinstance(digest, str) or not _SHA.fullmatch(digest):
                    raise TransferArchiveError("An active specification marker has an invalid digest.")
                version_key = "product_definitions/.versions/" + parts[2][:-5] + "/" + digest + ".json"
                version = files.get(("work", version_key))
                if version is None or version["sha256"] != digest:
                    raise TransferArchiveError("An active specification marker is missing its original version bytes.")
            continue
        ident = parts[2] if is_uploaded and len(parts) == 4 else parts[-1][:-5]
        try:
            parsed = parse_definition_snapshot(ident, original, source_path=entry["key"])
        except Exception as exc:
            raise TransferArchiveError("Specification storage contains a document that violates the installed executable safety policy.") from exc
        if is_uploaded and len(parts) == 4 and parsed.digest != parts[3][:-5]:
            raise TransferArchiveError("An immutable specification filename differs from its original bytes.")
    for submission in _rows(archive.records, "submissions"):
        if submission["publication_state"] != "published":
            continue
        prefix = submission["artifact_key"] + "/"
        entry = files.get(("submissions", prefix + "submission-manifest.json"))
        if entry is None and optional:
            if any(root == "submissions" and key.startswith(prefix) for root, key in files):
                raise TransferArchiveError("Included publication files require their original manifest.")
            continue
        if entry is None or entry["size"] > 2 * 1024**2:
            raise TransferArchiveError("A published receipt is missing its original manifest.")
        with archive.open_artifact(entry) as stream:
            manifest = _json(stream.read(2 * 1024**2 + 1))
        _verify_receipt(manifest, submission, archive.records)
        try:
            expected_inventory = _expected_inventory(manifest, "submission-manifest.json")
        except ValueError as exc:
            raise TransferArchiveError("A publication inventory is invalid.") from exc
        inputs = [item for name, item in expected_inventory.items() if name.startswith(JOB_INPUT_DIRNAME + "/")]
        if len(inputs) != 1 or inputs[0][0] != manifest["input_sha256"]:
            raise TransferArchiveError("A publication is missing its verified original input ZIP.")
        expected = manifest.get("files")
        if not isinstance(expected, list):
            raise TransferArchiveError("A publication inventory is invalid.")
        wanted = {prefix + "submission-manifest.json"}
        for item in expected:
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
                raise TransferArchiveError("A publication inventory is invalid.")
            key = prefix + validate_key(item["path"])
            stated = files.get(("submissions", key))
            wanted.add(key)
            if optional:
                reference = reference_index.get(("submissions", str(submission["submission_uuid"]), "publication_file", "submissions", key))
                if reference is None or (reference["expected_sha256"], reference["expected_size"]) != (item["sha256"], item["size"]):
                    raise TransferArchiveError("A publication reference differs from its original manifest.")
            if stated is None and optional:
                continue
            if stated is None or stated["sha256"] != item["sha256"] or stated["size"] != item["size"]:
                raise TransferArchiveError("A publication is missing files from its immutable inventory.")
        actual = {key for root, key in files if root == "submissions" and key.startswith(prefix)}
        if (actual - wanted or (not optional and (actual != wanted or prefix + "SUBMITTED" not in wanted or ("submissions", prefix[:-1] + "/" + JOB_OUTPUT_DIRNAME) not in dirs))):
            raise TransferArchiveError("A publication inventory has missing or unexpected files.")
    definitions = {item["digest"]: item for item in _rows(archive.records, "definitions")}
    found = set()
    for entry in archive.entries:
        if entry["sha256"] not in definitions:
            continue
        definition = definitions[entry["sha256"]]
        if entry["size"] > 1024**2:
            raise TransferArchiveError("An original specification exceeds its supported limit.")
        with archive.open_artifact(entry) as stream:
            original = stream.read(1024**2 + 1)
        try:
            parsed = parse_definition_snapshot(definition["product_ident"], original, source_path=definition["source_path"])
        except Exception as exc:
            raise TransferArchiveError("An original specification is not executable under the installed safety policy.") from exc
        if parsed.digest != definition["digest"] or parsed.document != definition["document"]:
            raise TransferArchiveError("Original specification bytes differ from their database revision.")
        found.add(parsed.digest)
    if not optional and found != set(definitions):
        raise TransferArchiveError("The package is missing original specification revisions.")
    accounts = {int(item["key"]): item["username"] for item in archive.records["accounts"]}
    for row in _rows(archive.records, "deliveries"):
        if row["s3_id"] is not None or row["is_deleted"]:
            continue
        entry = files.get(("incoming", accounts.get(row["user_id"], "") + "/" + row["filename"]))
        if entry is None and optional:
            continue
        if entry is None or entry["size"] != row["size_bytes"] or (row["content_sha256"] and entry["sha256"] != row["content_sha256"]):
            raise TransferArchiveError("An active local delivery is missing its verified ZIP.")


@dataclass
class ArtifactRestorePlan:
    archive: object
    roots: dict
    reuse: tuple
    create: tuple
    journal_path: Path | None = None
    _created_files: list = field(default_factory=list)
    _created_directories: list = field(default_factory=list)
    _created_links: list = field(default_factory=list)
    _journal_counts: tuple = (0, 0, 0)
    _journal_initialized: bool = False

    @property
    def warnings(self):
        if self.archive.records.get("profile") != "application":
            return ()
        result = []
        directories = {(item["root"], item["key"]) for item in self.archive.directories}
        for row in _rows(self.archive.records, "jobs"):
            key = "job_" + UUID(row["job_uuid"]).hex
            if ("work", key) not in directories:
                result.append("Job {} has database history but no retained working artifacts in this package.".format(row["job_uuid"]))
        if not self.archive.storage.get("boundaries"):
            result.append("This package contains no boundary snapshot. Provision required boundary packages before running QC.")
        return tuple(result)

    def _save_journal(self):
        if self.journal_path is None:
            return
        if not self._journal_initialized:
            header = {"version": 2, "package_sha256": self.archive.package_sha256,
                      "roots": {key: str(value.absolute()) for key, value in self.roots.items()}}
            header_bytes = canonical_json(header) + b"\n"
            if len(header_bytes) >= 64 * 1024:
                raise TransferArchiveError("The configured storage roots exceed the recovery journal header limit.")
            descriptor = os.open(self.journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(header_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            _sync_directory(self.journal_path.parent)
            self._journal_initialized = True
        counts = (len(self._created_files), len(self._created_links), len(self._created_directories))
        retained = tuple(min(old, new) for old, new in zip(self._journal_counts, counts))
        events = []
        if retained != self._journal_counts:
            events.append({"event": "truncate", "counts": retained})
        if counts != retained:
            events.append({"event": "add",
                "files": [{"root": entry["root"], "key": entry["key"], "device": device, "inode": inode}
                          for _path, device, inode, entry in self._created_files[retained[0]:]],
                "links": [{"name": path.name, "device": device, "inode": inode}
                          for path, device, inode in self._created_links[retained[1]:]],
                "directories": [{"path": str(path.absolute()), "device": device, "inode": inode}
                                for path, device, inode in self._created_directories[retained[2]:]]})
        if not events:
            return
        lines = [canonical_json(event) + b"\n" for event in events]
        if any(len(line) >= 64 * 1024 for line in lines):
            raise TransferArchiveError("An artifact recovery journal event exceeds its size limit.")
        payload = b"".join(lines)
        descriptor = os.open(self.journal_path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        previous = os.fstat(descriptor)
        try:
            if not stat.S_ISREG(previous.st_mode) or previous.st_size + len(payload) > 128 * 1024**2:
                raise TransferArchiveError("The artifact recovery journal is unsafe or exceeds its limit.")
            with os.fdopen(descriptor, "ab") as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # A synchronous append failure must not leave a torn record before
            # a later rollback event. Process death is handled by the loader.
            recovery = os.open(self.journal_path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                current = os.fstat(recovery)
                if (current.st_dev, current.st_ino) == (previous.st_dev, previous.st_ino):
                    os.ftruncate(recovery, previous.st_size)
                    os.fsync(recovery)
            finally:
                os.close(recovery)
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
        self._journal_counts = counts

    def _load_journal(self):
        if self.journal_path is None or not os.path.lexists(self.journal_path):
            return
        with open_regular(self.journal_path) as stream:
            metadata = os.fstat(stream.fileno())
            if metadata.st_size > 128 * 1024**2:
                raise TransferArchiveError("The artifact recovery journal is oversized.")
            header = stream.readline(64 * 1024)
            if not header.endswith(b"\n"):
                raise TransferArchiveError("The artifact recovery journal header is incomplete.")
            document = _json(header)
            if not isinstance(document, dict) or set(document) != {"version", "package_sha256", "roots"} or document["version"] != 2:
                raise TransferArchiveError("The artifact recovery journal format is unsupported.")
            roots = {key: str(value.absolute()) for key, value in self.roots.items()}
            if document["package_sha256"] != self.archive.package_sha256 or document["roots"] != roots:
                raise TransferArchiveError("The artifact recovery journal belongs to a different package or storage configuration.")
            document.update(files=[], links=[], directories=[])
            valid_bytes = len(header)
            records = 0
            for line in iter(lambda: stream.readline(64 * 1024), b""):
                if len(line) >= 64 * 1024:
                    raise TransferArchiveError("An artifact recovery journal event exceeds its size limit.")
                if not line.endswith(b"\n"):
                    # Every publication follows a fully fsynced newline-framed
                    # event. A torn final append therefore owns no new object.
                    break
                event = _json(line)
                records += 1
                if records > self.archive.limits.max_members * 4 + 128 or not isinstance(event, dict):
                    raise TransferArchiveError("The artifact recovery journal contains too many events.")
                if event.get("event") == "add" and set(event) == {"event", "files", "links", "directories"}:
                    for name in ("files", "links", "directories"):
                        if not isinstance(event[name], list):
                            raise TransferArchiveError("The artifact recovery journal event is invalid.")
                        document[name].extend(event[name])
                elif event.get("event") == "truncate" and set(event) == {"event", "counts"} and isinstance(event["counts"], list) and len(event["counts"]) == 3:
                    for name, count in zip(("files", "links", "directories"), event["counts"]):
                        if type(count) is not int or count < 0 or count > len(document[name]):
                            raise TransferArchiveError("The artifact recovery journal truncation is invalid.")
                        del document[name][count:]
                else:
                    raise TransferArchiveError("The artifact recovery journal event is invalid.")
                valid_bytes += len(line)
        if valid_bytes < metadata.st_size:
            descriptor = os.open(self.journal_path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                current = os.fstat(descriptor)
                if (current.st_dev, current.st_ino, current.st_size) != (metadata.st_dev, metadata.st_ino, metadata.st_size):
                    raise TransferArchiveError("The artifact recovery journal changed concurrently.")
                os.ftruncate(descriptor, valid_bytes)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        files = {(entry["root"], entry["key"]): entry for entry in self.archive.entries}
        try:
            for item in document["files"]:
                entry = files[(item["root"], item["key"])]
                if set(item) != {"root", "key", "device", "inode"} or type(item["device"]) is not int or type(item["inode"]) is not int:
                    raise ValueError
                self._created_files.append((self.roots[entry["root"]] / entry["key"], item["device"], item["inode"], entry))
            for item in document["links"]:
                if set(item) != {"name", "device", "inode"} or item["name"] not in {".boundary-current", "raster", "vector"} or type(item["device"]) is not int or type(item["inode"]) is not int:
                    raise ValueError
                self._created_links.append((self.roots["boundaries"] / item["name"], item["device"], item["inode"]))
            for item in document["directories"]:
                path = Path(item["path"])
                if set(item) != {"path", "device", "inode"} or type(item["device"]) is not int or type(item["inode"]) is not int or not path.is_absolute() or not any(path == root.absolute() or root.absolute() in path.parents or path in root.absolute().parents for root in self.roots.values()):
                    raise ValueError
                self._created_directories.append((path, item["device"], item["inode"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise TransferArchiveError("The artifact recovery journal is invalid.") from exc
        self._journal_initialized = True
        self._journal_counts = (len(self._created_files), len(self._created_links), len(self._created_directories))

    @property
    def summary(self):
        return {"create_files": len(self.create), "reuse_files": len(self.reuse),
                "bytes": sum(item["size"] for item in self.create),
                "directories": len(self.archive.directories)}

    @property
    def delivery_files(self):
        return inspect_delivery_files(self.archive, roots=self.roots)["files"]

    def _directory(self, path):
        path = Path(path)
        if path.is_symlink():
            raise TransferArchiveError("A destination directory became a symbolic link.")
        if path.exists():
            if not path.is_dir():
                raise TransferArchiveError("A destination directory is occupied by a file.")
            return
        self._directory(path.parent)
        try:
            path.mkdir(mode=0o750)
            metadata = path.stat(follow_symlinks=False)
            self._created_directories.append((path, metadata.st_dev, metadata.st_ino))
            _sync_directory(path.parent)
            self._save_journal()
        except FileExistsError:
            if path.is_symlink() or not path.is_dir():
                raise TransferArchiveError("A destination directory was occupied concurrently.")

    def apply(self, *, rollback_on_error=True):
        """Publish complete files with link(O_EXCL); all existing bytes are kept."""

        try:
            for path, device, inode in self._created_directories:
                if not os.path.lexists(path):
                    continue
                metadata = path.lstat()
                if (metadata.st_dev, metadata.st_ino) != (device, inode) or not stat.S_ISDIR(metadata.st_mode):
                    raise TransferArchiveError("A staged directory was replaced after interruption.")
                os.chmod(path, 0o750)
            for entry in self.archive.directories:
                self._directory(self.roots[entry["root"]] / entry["key"])
            for entry in self.archive.entries:
                target = self.roots[entry["root"]] / entry["key"]
                self._directory(target.parent)
                if os.path.lexists(target):
                    _require_matching(target, self.roots[entry["root"]], entry)
                    continue
                temporary = None
                try:
                    staging = self.roots[entry["root"]] / ".record-transfer-staging"
                    self._directory(staging)
                    if staging.stat().st_dev != target.parent.stat().st_dev:
                        raise TransferArchiveError("A storage root contains a nested mount; configure separate roots before restoring artifacts.")
                    with tempfile.NamedTemporaryFile(dir=staging, prefix=".record-transfer-", delete=False) as output:
                        temporary = Path(output.name)
                        mode = 0o440 if entry["root"] == "boundaries" and entry["key"].startswith(".boundary-generations/") else 0o640
                        os.fchmod(output.fileno(), mode)
                        self.archive.copy_artifact(entry, output)
                        output.flush()
                        os.fsync(output.fileno())
                        metadata = os.fstat(output.fileno())
                    ownership = (target, metadata.st_dev, metadata.st_ino, entry)
                    self._created_files.append(ownership)
                    # The durable intent precedes publication. On process death,
                    # only this inode can later be removed by recovery.
                    self._save_journal()
                    # Revalidate parents immediately before publication. Storage
                    # is administrator-owned and maintenance excludes app writers.
                    parent_key = str(Path(entry["key"]).parent)
                    _safe_directory(self.roots[entry["root"]], "" if parent_key == "." else parent_key)
                    try:
                        os.link(temporary, target, follow_symlinks=False)
                    except FileExistsError:
                        _require_matching(target, self.roots[entry["root"]], entry)
                        self._created_files.remove(ownership)
                        self._save_journal()
                    _sync_directory(target.parent)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            for path, device, inode in reversed(self._created_directories):
                if "boundaries" in self.roots and self.roots["boundaries"] / ".boundary-generations" in path.parents:
                    metadata = path.lstat()
                    if (metadata.st_dev, metadata.st_ino) != (device, inode):
                        raise TransferArchiveError("A boundary directory changed during publication.")
                    os.chmod(path, 0o550)
                    _sync_directory(path)
            self._activate_boundaries()
            return [str(item[0]) for item in self._created_files]
        except Exception:
            if rollback_on_error:
                self.rollback()
            raise

    def _activate_boundaries(self):
        state = self.archive.storage.get("boundaries", {})
        if state.get("mode") != "managed":
            return
        root, generation = self.roots["boundaries"], state["generation"]
        generation_path = root / ".boundary-generations" / generation
        for directory in (generation_path / "raster", generation_path / "vector"):
            _safe_directory(directory)
        # Recreate only application-defined links, never ZIP-supplied targets.
        links = {".boundary-current": ".boundary-generations/" + generation,
                 "raster": ".boundary-current/raster", "vector": ".boundary-current/vector"}
        for name, value in links.items():
            target = root / name
            if os.path.lexists(target):
                if not target.is_symlink() or os.readlink(target) != value:
                    raise TransferArchiveError("Existing boundary activation differs from the package.")
                continue
            temporary = root / (".record-transfer-link-" + os.urandom(16).hex())
            try:
                os.symlink(value, temporary)
                _sync_directory(root)
                metadata = temporary.lstat()
                ownership = (target, metadata.st_dev, metadata.st_ino)
                self._created_links.append(ownership)
                self._save_journal()
                try:
                    os.link(temporary, target, follow_symlinks=False)
                except FileExistsError:
                    if not target.is_symlink() or os.readlink(target) != value:
                        raise TransferArchiveError("Boundary activation was occupied concurrently.")
                    self._created_links.remove(ownership)
                    self._save_journal()
            finally:
                temporary.unlink(missing_ok=True)
        _sync_directory(root)

    def rollback(self):
        """Remove only unchanged filesystem objects this plan actually created."""

        failures = []
        # Only owned generation directories may have been frozen after copying.
        for target, device, inode in self._created_directories:
            try:
                metadata = target.lstat()
                if (metadata.st_dev, metadata.st_ino) == (device, inode) and stat.S_ISDIR(metadata.st_mode):
                    os.chmod(target, 0o750)
            except FileNotFoundError:
                pass
        for target, device, inode in reversed(self._created_links):
            try:
                metadata = target.lstat()
                if (metadata.st_dev, metadata.st_ino) != (device, inode):
                    raise OSError("A created link was replaced.")
                target.unlink()
                _sync_directory(target.parent)
            except FileNotFoundError:
                pass
            except OSError:
                failures.append(str(target))
        for target, device, inode, entry in reversed(self._created_files):
            try:
                metadata = target.lstat()
                if (metadata.st_dev, metadata.st_ino) != (device, inode) or not stat.S_ISREG(metadata.st_mode):
                    raise OSError("A created artifact was replaced.")
                _require_matching(target, self.roots[entry["root"]], entry)
                target.unlink()
                _sync_directory(target.parent)
            except FileNotFoundError:
                pass
            except (OSError, TransferArchiveError):
                failures.append(str(target))
        for target, device, inode in reversed(self._created_directories):
            try:
                metadata = target.lstat()
                if (metadata.st_dev, metadata.st_ino) == (device, inode) and stat.S_ISDIR(metadata.st_mode):
                    target.rmdir()
                    _sync_directory(target.parent)
            except FileNotFoundError:
                pass
            except OSError:
                failures.append(str(target))
        if failures:
            raise TransferArchiveError("Some staged artifacts were retained after rollback; keep maintenance enabled and review the transfer journal.")
        self._created_links.clear()
        self._created_files.clear()
        self._created_directories.clear()
        self._save_journal()


def _require_matching(path, root, entry):
    with open_regular(path, storage_root=root) as stream:
        actual = _hash(stream, entry["size"])
    if actual != (entry["sha256"], entry["size"]):
        raise TransferArchiveError("Existing storage conflicts with the package; nothing may be overwritten.")


def inspect_delivery_files(archive, *, roots=None):
    """Describe delivery ZIP reuse/conflicts without changing SQL or storage.

    Only the reviewed owner's canonical incoming path is inspected. A file's
    package checksum and a historical job's recorded checksum are distinct
    evidence; missing historical checksums remain visible.
    """

    if "references" in archive.storage:
        from .artifact_references import inspect_optional_delivery_files
        return inspect_optional_delivery_files(archive, roots=roots or storage_roots())
    roots = {key: Path(value) for key, value in (roots or storage_roots()).items()}
    accounts = {int(row["key"]): row["username"] for row in archive.records.get("accounts", [])}
    entries = {(entry["root"], entry["key"]): entry for entry in archive.entries}
    files, conflicts = [], []
    jobs = {}
    for row in _rows(archive.records, "jobs"):
        if row.get("delivery_id") is not None:
            jobs.setdefault(str(row["delivery_id"]), []).append(row)
    for row in _rows(archive.records, "deliveries"):
        related = jobs.get(str(row["id"]), [])
        owner = accounts.get(row["user_id"])
        item = {"delivery_id": row["id"], "filename": row["filename"], "owner": owner or "",
                "size": row["size_bytes"], "sha256": row.get("content_sha256") or "",
                "job_count": len(related), "status": "", "file_status": "", "message": ""}
        reason = ""
        if row["s3_id"] is not None:
            item.update(status="remote", file_status="remote", message="Remote input requires separately configured access.")
        elif owner is None:
            if row["is_deleted"]:
                item.update(status="historical_absent", file_status="historical_absent", message="Deleted delivery has no retained owner or original ZIP.")
            else:
                reason = "The active local delivery has no identifiable storage owner."
        else:
            try:
                if Path(row["filename"]).name != row["filename"] or not row["filename"].lower().endswith(".zip"):
                    raise TransferArchiveError("The delivery filename is not a safe ZIP filename.")
                key = validate_key(owner + "/" + row["filename"])
                entry = entries.get(("incoming", key))
                if entry is None:
                    if row["is_deleted"]:
                        item.update(status="historical_absent", file_status="historical_absent", message="No original upload is included for this deleted delivery.")
                    else:
                        reason = "The package is missing the active delivery's verified original ZIP."
                else:
                    item["sha256"] = entry["sha256"]
                    if entry["size"] != row["size_bytes"] or (row.get("content_sha256") and entry["sha256"] != row["content_sha256"]):
                        reason = "The packaged ZIP differs from the delivery's recorded checksum or size."
                    elif "incoming" not in roots:
                        reason = "Incoming ZIP storage is not configured in this installation."
                    else:
                        target = roots["incoming"] / key
                        if os.path.lexists(target):
                            _require_matching(target, roots["incoming"], entry)
                            item.update(status="retained_verified", file_status="retained_verified", message="Matching packaged ZIP already exists on this server; it will be reused.")
                        else:
                            # Check every existing parent even when the leaf is
                            # missing; never classify a symlink as a safe create.
                            _safe_directory(roots["incoming"], owner, required=False)
                            item.update(status="packaged", file_status="packaged", message="Verified original ZIP is included and will be added without replacing files.")
                    if not reason and any(not _SHA.fullmatch(job.get("input_sha256") or "") for job in related):
                        item.update(status="unverified_history", message=item["message"] + " Some historical runs have no recorded input checksum.")
                    elif not reason and any(job.get("input_sha256") != entry["sha256"] for job in related):
                        item.update(status="unverified_history", message=item["message"] + " Some historical runs checked different bytes and need their separate retained publication input.")
            except (OSError, ValueError):
                reason = "Existing ZIP storage differs from the package or cannot be read safely."
        if reason:
            item.update(status="missing" if "missing" in reason else "different", file_status="conflict", message=reason)
            conflicts.append({"key": "deliveries:" + str(row["id"]), "resource": "deliveries",
                              "source_key": str(row["id"]), "reason": reason, "choices": ["skip"]})
        files.append(item)
    return {"files": files, "conflicts": conflicts}


def additive_archive(archive, included):
    """Select reviewed business branches without importing deployment state.

    Validate the complete original package before filtering it. Artifacts keep
    their ZIP member path and checksum; only safe destination keys may change.
    Specifications go to immutable digest paths, while current specification
    markers and boundary generations/activation are never adopted by a merge.
    """

    _validate_package_artifacts(archive)
    if archive.records.get("profile") != "application":
        return archive
    if not isinstance(included, dict):
        raise TransferArchiveError("Additive artifact selection is invalid.")
    payload = deepcopy(archive.records)
    for name, rows in payload["records"].items():
        key = {"jobs": "job_uuid", "submissions": "submission_uuid"}.get(name, "id")
        selected = {str(value) for value in included.get(name, ())}
        payload["records"][name] = [row for row in rows if str(row[key]) in selected]
    storage = {"boundaries": {}}
    if "compatibility" in archive.storage:
        storage["compatibility"] = archive.storage["compatibility"]
    if "references" in archive.storage:
        from .artifact_references import filter_references
        storage["references"] = filter_references(archive.storage["references"], included)
    selected = replace(archive, records=payload, entries=(), directories=(), storage=storage)
    allowed = _allowed_paths(selected)
    entries = {}
    definitions = _rows(payload, "definitions")
    definition_digests = {row["digest"] for row in definitions}
    originals = {}
    for entry in archive.entries:
        parts = Path(entry["key"]).parts
        configuration = entry["root"].startswith("product-") or (
            entry["root"] == "work" and parts[0] == "product_definitions"
        )
        if entry["sha256"] in definition_digests and entry["key"].endswith(".json"):
            originals.setdefault(entry["sha256"], entry)
        if entry["root"] == "boundaries" or configuration:
            continue
        if allowed(entry["root"], entry["key"]):
            entries[(entry["root"], entry["key"])] = dict(entry)
    for definition in definitions:
        digest = definition["digest"]
        original = originals.get(digest)
        if original is None and "references" in storage:
            continue
        if original is None:
            raise TransferArchiveError("The selected graph is missing original specification bytes.")
        entry = {**original, "root": "work", "key": "product_definitions/.versions/" + definition["product_ident"] + "/" + digest + ".json"}
        entries[(entry["root"], entry["key"])] = entry
    directories = {}
    for item in archive.directories:
        if item["root"] == "boundaries" or (item["root"] == "work" and item["key"].startswith("product_definitions")):
            continue
        if allowed(item["root"], item["key"], True):
            directories[(item["root"], item["key"])] = dict(item)
    for entry in entries.values():
        parts = Path(entry["key"]).parts
        for length in range(1, len(parts)):
            key = "/".join(parts[:length])
            if allowed(entry["root"], key, True):
                directories[(entry["root"], key)] = {"root": entry["root"], "key": key}
    selected = replace(selected, entries=tuple(entries[key] for key in sorted(entries)),
                       directories=tuple(directories[key] for key in sorted(directories)))
    _validate_package_artifacts(selected)
    return selected


def inspect_retained_artifact_conflicts(archive, *, roots=None):
    """Expose retained job/publication collisions as connected-graph choices.

    Call with the reviewed additive archive so skipped branches and deployment
    configuration are already excluded. Every reported decision is skip-only;
    this inspector never authorizes replacing or repairing existing bytes.
    """

    roots = {key: Path(value) for key, value in (roots or storage_roots()).items()}
    conflicts = []
    branches = []
    for resource, rows in (("jobs", _rows(archive.records, "jobs")),
                           ("submissions", _rows(archive.records, "submissions"))):
        for row in rows:
            if resource == "submissions" and row["publication_state"] != "published":
                continue
            source_key = str(row["job_uuid"] if resource == "jobs" else row["submission_uuid"])
            root = "work" if resource == "jobs" else "submissions"
            prefix = "job_" + UUID(source_key).hex if resource == "jobs" else row["artifact_key"]
            branches.append((resource, row, source_key, root, prefix))
    # Index each inventory member once. Scanning every package member again
    # for every historical job becomes quadratic on a large installation.
    owners = {(root, prefix) for _resource, _row, _key, root, prefix in branches}
    grouped_files, grouped_directories = {}, {}
    for directory, items, grouped in ((False, archive.entries, grouped_files),
                                      (True, archive.directories, grouped_directories)):
        for item in items:
            parts = Path(item["key"]).parts
            for length in range(len(parts) if directory else len(parts) - 1, 0, -1):
                owner = (item["root"], "/".join(parts[:length]))
                if owner in owners:
                    grouped.setdefault(owner, []).append(item)
                    break
    for resource, row, source_key, root, prefix in branches:
        entries = tuple(grouped_files.get((root, prefix), ()))
        directories = tuple(grouped_directories.get((root, prefix), ()))
        if "references" in archive.storage and not entries and not directories:
            # A records-only graph makes no claim about or changes to unrelated
            # retained bytes. Their presence cannot prevent retaining history.
            continue
        payload = {**archive.records, "records": {**archive.records["records"],
            "jobs": [row] if resource == "jobs" else [],
            "submissions": [row] if resource == "submissions" else []}}
        branch_storage = {"boundaries": {}}
        if "references" in archive.storage:
            branch_storage["references"] = {**archive.storage["references"], "items": [item for item in archive.storage["references"]["items"]
                if item["resource"] == resource and item["source_key"] == source_key]}
        branch = replace(archive, records=payload, entries=entries, directories=directories, storage=branch_storage)
        try:
            if root not in roots:
                raise TransferArchiveError("Required retained storage is not configured.")
            _preflight_retained_trees(branch, roots)
            for entry in entries:
                path = roots[root] / entry["key"]
                _safe_directory(roots[root], str(Path(entry["key"]).parent), required=False)
                if os.path.lexists(path):
                    _require_matching(path, roots[root], entry)
        except (OSError, ValueError):
            reason = ("Retained QC job artifacts conflict with this package or are unsafe."
                      if resource == "jobs" else
                      "Retained submission files conflict with this immutable publication inventory or are unsafe.")
            conflicts.append({"key": resource + ":" + source_key, "resource": resource,
                              "source_key": source_key, "reason": reason, "choices": ["skip"]})
    return conflicts


def _preflight_retained_trees(archive, roots):
    """An unlisted existing file must not change a restored immutable receipt."""

    expected_files = {(item["root"], item["key"]) for item in archive.entries}
    payload_files = set(expected_files)
    expected_directories = {(item["root"], item["key"]) for item in archive.directories}
    reference_files = {}
    if "references" in archive.storage:
        for item in archive.storage["references"]["items"]:
            digest = item["expected_sha256"] or item["observed_sha256"]
            size = item["expected_size"] if item["expected_size"] is not None else item["observed_size"]
            if item["kind"] == "file" and item["root"] and digest is not None and size is not None:
                reference_files[(item["root"], item["key"])] = {"sha256": digest, "size": size}
                for length in range(1, len(Path(item["key"]).parts)):
                    expected_directories.add((item["root"], "/".join(Path(item["key"]).parts[:length])))
        expected_files.update(reference_files)
    trees = [("submissions", item["artifact_key"]) for item in _rows(archive.records, "submissions") if item["publication_state"] == "published"]
    if "references" in archive.storage:
        # Only trees receiving payloads are restore destinations. Optional
        # historical references never claim ownership of a retained directory.
        trees = [(name, key) for name, key in trees if any(root == name and child.startswith(key + "/")
                 for root, child in payload_files)]
    trees += [("boundaries", key) for root, key in expected_directories if root == "boundaries" and
              (key in {"raster", "vector"} or (len(Path(key).parts) == 2 and Path(key).parts[0] == ".boundary-generations"))]
    for name, key in trees:
        if name not in roots or not os.path.lexists(roots[name] / key):
            continue
        stack = [key]
        while stack:
            current = stack.pop()
            directory = _safe_directory(roots[name], current)
            if (name, current) not in expected_directories:
                raise TransferArchiveError("Existing retained storage contains a directory outside the package inventory.")
            for entry in os.scandir(directory):
                child = current + "/" + entry.name
                if entry.is_symlink():
                    raise TransferArchiveError("Existing retained storage contains a filesystem link.")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(child)
                elif not entry.is_file(follow_symlinks=False) or (name, child) not in expected_files:
                    raise TransferArchiveError("Existing retained storage contains a file outside the package inventory.")
                elif (name, child) in reference_files:
                    _require_matching(Path(entry.path), roots[name], reference_files[(name, child)])
    for job in _rows(archive.records, "jobs"):
        key = "job_" + UUID(job["job_uuid"]).hex
        if "references" in archive.storage and not any(root == "work" and child.startswith(key + "/") for root, child in payload_files):
            continue
        if "work" not in roots or not os.path.lexists(roots["work"] / key):
            continue
        stack = [(key, False)]
        while stack:
            current, scratch = stack.pop()
            directory = _safe_directory(roots["work"], current)
            for entry in os.scandir(directory):
                child = current + "/" + entry.name
                if entry.is_symlink():
                    raise TransferArchiveError("Existing retained job storage contains a filesystem link.")
                if entry.is_dir(follow_symlinks=False):
                    runtime = scratch or (current == key and entry.name in {JOB_INPUT_DIRNAME, JOB_TMP_DIRNAME})
                    if not runtime and ("work", child) not in expected_directories:
                        raise TransferArchiveError("Existing retained job storage contains a directory outside the package inventory.")
                    stack.append((child, runtime))
                elif entry.is_file(follow_symlinks=False):
                    runtime = scratch or (current == key and entry.name.lower().endswith((".log", ".stdout", ".pre")))
                    if not runtime and ("work", child) not in expected_files:
                        raise TransferArchiveError("Existing retained job storage contains a file outside the package inventory.")
                    if not runtime and ("work", child) in reference_files:
                        _require_matching(Path(entry.path), roots["work"], reference_files[("work", child)])
                else:
                    raise TransferArchiveError("Existing retained job storage contains a special filesystem object.")


def plan_artifact_restore(archive, *, roots=None, journal_path=None):
    """Perform read-only conflict and namespace checks before any file writes."""

    _validate_package_artifacts(archive)
    roots = {key: Path(value) for key, value in (roots or storage_roots()).items()}
    _preflight_retained_trees(archive, roots)
    create, reuse = [], []
    for directory, entries in ((False, archive.entries), (True, archive.directories)):
        for entry in entries:
            if entry["root"] not in roots:
                raise TransferArchiveError("A required storage root is not configured in this installation.")
            root, key = roots[entry["root"]], entry["key"]
            current = root
            for part in (None, *Path(key).parts[:-1]):
                if part is not None:
                    current /= part
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise TransferArchiveError("A destination storage parent is unsafe or occupied.")
            target = root / key
            if directory:
                if os.path.lexists(target) and (target.is_symlink() or not target.is_dir()):
                    raise TransferArchiveError("A destination directory is unsafe or occupied.")
            elif os.path.lexists(target):
                _require_matching(target, root, entry)
                reuse.append(entry)
            else:
                create.append(entry)
    boundary = archive.storage.get("boundaries", {})
    if boundary.get("mode") == "managed":
        if "boundaries" not in roots:
            raise TransferArchiveError("Boundary storage is not configured.")
        links = {".boundary-current": ".boundary-generations/" + boundary["generation"],
                 "raster": ".boundary-current/raster", "vector": ".boundary-current/vector"}
        for name, expected in links.items():
            path = roots["boundaries"] / name
            if os.path.lexists(path) and (not path.is_symlink() or os.readlink(path) != expected):
                raise TransferArchiveError("Existing boundary activation conflicts with the package.")
    plan = ArtifactRestorePlan(archive, roots, tuple(reuse), tuple(create), Path(journal_path) if journal_path is not None else None)
    plan._load_journal()
    return plan
