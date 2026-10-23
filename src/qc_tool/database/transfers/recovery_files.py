"""Optional, confined durable files accompanying a complete PostgreSQL copy.

This inventory deliberately does not query ORM models: native preservation must
remain available when the source schema differs from the installed models.
Runtime work, private control state and secrets need their own recovery channel.
Files are restored with the existing exclusive-create journal, never replaced.
"""

from dataclasses import replace
import os
from pathlib import Path
import re

from qc_tool.common import JOB_INPUT_DIRNAME, JOB_TMP_DIRNAME

from .archive import ArtifactSource, ArchiveLimits, TransferArchiveError, _hash, open_regular, validate_key
from .artifacts import ArtifactInventory, ArtifactRestorePlan, _safe_directory, storage_roots
from .contracts import digest


VERSION = 1
_JOB = re.compile(r"^job_[0-9a-f]{32}$")
EXCLUSIONS = (
    "PostgreSQL cluster roles, deployment configuration and encryption keys",
    "Private maintenance, transfer, credential and storage-trash journals",
    "Partial uploads, worker input/scratch directories and diagnostic logs",
    "Remote objects, files outside configured business storage and active configuration pointers",
)


def allowed(root, key, directory=False):
    """One namespace policy shared by collection, review and restoration."""
    validate_key(key)
    parts = Path(key).parts
    if any(part.startswith(".qc-tool-") or part in {".staging", ".trash"} for part in parts):
        return False
    if root == "incoming":
        return len(parts) == 1 if directory else (len(parts) == 2 and parts[-1].lower().endswith(".zip"))
    if root == "work":
        if _JOB.fullmatch(parts[0]):
            if len(parts) > 1 and parts[1] in {JOB_INPUT_DIRNAME, JOB_TMP_DIRNAME}:
                return False
            return directory or not parts[-1].lower().endswith((".log", ".stdout", ".pre"))
        if parts[0] == "product_definitions":
            from .artifacts import _spec_directory, _spec_path
            if len(parts) > 1 and parts[1] == ".state":
                return False
            return _spec_directory(key) if directory else _spec_path(key)
        return False
    if root == "submissions":
        return not any(part.startswith(".") for part in parts)
    if root == "boundaries":
        return parts[0] in {"raster", "vector", ".boundary-generations"}
    if re.fullmatch(r"product-[0-9]+", root):
        return not directory and len(parts) == 1 and parts[0].endswith(".json")
    return False


def collect(*, roots=None, limits=None):
    """Inventory all retained business files, including unlinked legacy ZIPs."""
    roots = roots or storage_roots()
    limits = limits or ArchiveLimits()
    sources, directories, unavailable = [], [], []
    visited = 0

    def visit(root_name, root, key):
        nonlocal visited
        visited += 1
        if visited > limits.max_members * 4 or len(sources) + len(directories) >= limits.max_members - 2:
            raise TransferArchiveError("Retained storage exceeds the configured backup inventory limit.")
        target = root / key
        # Known managed boundary links are configuration, not payloads. Their
        # original immutable generations are copied independently below.
        if root_name == "boundaries" and key in {"raster", "vector"} and target.is_symlink():
            return
        if not allowed(root_name, key, target.is_dir()):
            return
        if target.is_symlink():
            raise TransferArchiveError("Recovery storage contains a symbolic link in a retained namespace.")
        if target.is_dir():
            if not allowed(root_name, key, True):
                return
            directories.append({"root": root_name, "key": key})
            with os.scandir(target) as children:
                for child in children:
                    visit(root_name, root, key + "/" + child.name)
        elif allowed(root_name, key):
            with open_regular(target, storage_root=root):
                pass
            sources.append(ArtifactSource(root_name, key, target, root))

    for name, configured in roots.items():
        root = Path(configured)
        if _safe_directory(root, required=False) is None:
            unavailable.append(name)
            continue
        with os.scandir(root) as children:
            for entry in children:
                visit(name, root, entry.name)
    return ArtifactInventory(tuple(sorted(sources, key=lambda item: (item.root, item.key))),
        tuple(sorted(directories, key=lambda item: (item["root"], item["key"]))),
        {"recovery_files": {"version": VERSION, "scope": "retained_business_storage",
                            "unavailable_roots": sorted(unavailable), "exclusions": list(EXCLUSIONS)}},
        tuple("Storage area {} is unavailable; its files are not included.".format(name) for name in unavailable))


def snapshot(*, limits, roots=None):
    inventory = collect(roots=roots, limits=limits)
    entries, total = [], 0
    for source in inventory.sources:
        with open_regular(source.path, storage_root=source.storage_root) as stream:
            before = os.fstat(stream.fileno())
            checksum, size = _hash(stream, limits.max_member_bytes)
            after = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise TransferArchiveError("A retained file changed during backup review. Isolate external writers and retry.")
        total += size
        if total > limits.max_total_bytes or len(entries) >= limits.max_members - 2:
            raise TransferArchiveError("The retained files exceed the configured backup limits.")
        entries.append({"root": source.root, "key": source.key, "sha256": checksum, "size": size})
    fingerprint = digest({"entries": entries, "directories": inventory.directories, "storage": inventory.storage})
    return inventory, entries, fingerprint, total


def validate(archive):
    contract = archive.storage.get("recovery_files")
    if contract is None:
        if archive.directories or any(item["root"] != "database" for item in archive.entries):
            raise TransferArchiveError("A native backup has files without a supported storage contract.")
        if set(archive.storage) - {"compatibility"}:
            raise TransferArchiveError("The native backup storage contract is unsupported.")
        return
    if (not isinstance(contract, dict) or set(contract) != {"version", "scope", "unavailable_roots", "exclusions"}
            or type(contract["version"]) is not int or contract["version"] != VERSION
            or contract["scope"] != "retained_business_storage"
            or contract["exclusions"] != list(EXCLUSIONS)
            or not isinstance(contract["unavailable_roots"], list)
            or len(contract["unavailable_roots"]) > 1000
            or any(not isinstance(name, str) or len(name) > 40 for name in contract["unavailable_roots"])
            or set(archive.storage) - {"recovery_files", "compatibility"}):
        raise TransferArchiveError("The native backup file contract is unsupported.")
    for is_directory, items in ((False, archive.entries), (True, archive.directories)):
        for item in items:
            if item["root"] == "database" and not is_directory:
                continue
            if not allowed(item["root"], item["key"], is_directory):
                raise TransferArchiveError("The backup contains a file outside retained business storage.")


def plan_restore(archive, *, journal_path, include_files=True, roots=None):
    """Reuse the durable POSIX publication journal without activating config."""
    from .artifacts import _require_matching

    validate(archive)
    roots = {name: Path(path) for name, path in (roots or storage_roots()).items()}
    entries = tuple(entry for entry in archive.entries if entry["root"] != "database") if include_files else ()
    # Source specification directories and their old flat compatibility files
    # are discovery/activation locations. Preserve bytes in the existing inert,
    # immutable version namespace instead of selecting source configuration.
    translated = {}
    legacy_boundary_prefix = ".boundary-generations/legacy-" + archive.package_sha256[:32]
    def destination(entry):
        if entry["root"] == "boundaries" and Path(entry["key"]).parts[0] in {"raster", "vector"}:
            return {**entry, "key": legacy_boundary_prefix + "/" + entry["key"]}
        return entry
    for entry in entries:
        entry = destination(entry)
        parts = Path(entry["key"]).parts
        if entry["root"].startswith("product-") or (
            entry["root"] == "work" and len(parts) == 2 and parts[0] == "product_definitions"
        ):
            from qc_tool.product_security import canonical_product_ident
            ident = parts[-1][:-5]
            if canonical_product_ident(ident) is None:
                raise TransferArchiveError("A retained specification has an invalid product identity.")
            entry = {**entry, "root": "work", "key": "product_definitions/.versions/" + ident + "/" + entry["sha256"] + ".json"}
        identity = (entry["root"], entry["key"])
        previous = translated.get(identity)
        if previous is not None and (previous["sha256"], previous["size"]) != (entry["sha256"], entry["size"]):
            raise TransferArchiveError("Retained specification copies disagree.")
        translated.setdefault(identity, entry)
    entries = tuple(translated.values())
    directories = tuple(destination(entry) for entry in archive.directories if not entry["root"].startswith("product-")) if include_files else ()
    selected = replace(archive, entries=entries, directories=directories, storage={})
    create, reuse = [], []
    for directory, values in ((False, entries), (True, directories)):
        for entry in values:
            if entry["root"] not in roots:
                raise TransferArchiveError("A required backup storage root is not configured.")
            root, key = roots[entry["root"]], entry["key"]
            current = root
            for part in (None, *Path(key).parts[:-1]):
                if part is not None:
                    current /= part
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise TransferArchiveError("A backup destination parent is unsafe or occupied.")
            target = root / key
            if directory:
                if os.path.lexists(target) and (target.is_symlink() or not target.is_dir()):
                    raise TransferArchiveError("A backup destination directory is unsafe or occupied.")
            elif os.path.lexists(target):
                _require_matching(target, root, entry)
                reuse.append(entry)
            else:
                create.append(entry)
    plan = ArtifactRestorePlan(selected, roots, tuple(reuse), tuple(create), Path(journal_path))
    plan._load_journal()
    return plan
