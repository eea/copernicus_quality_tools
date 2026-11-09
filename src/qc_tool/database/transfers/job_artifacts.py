"""Retained job bytes under the stable pre-existing transfer namespace.

Physical layout is owned by ``qc_tool.jobs``. Archive keys stay ``job_<hex>``;
canonical inner role namespaces remain separate to prevent basename collisions.
Diagnostic logs and materialized inputs/scratch remain outside this contract.
"""

import os
from pathlib import Path
from uuid import UUID

from qc_tool.jobs import read_job_context, resolve_job_paths

from .archive import ArtifactSource, TransferArchiveError, _hash, open_regular, validate_key


def job_archive_key(job_uuid):
    return "job_" + UUID(str(job_uuid)).hex


def collect_job_artifacts(root, job_uuid, *, target=None, native=False):
    """Return exact sources/directories without moving or rewriting any bytes."""
    root = Path(root)
    try:
        paths = target[0] if target else resolve_job_paths(root, job_uuid)
        if not paths.directory.exists():
            return (), ()
        context = target[1] if target else read_job_context(paths)
    except (OSError, ValueError) as error:
        raise TransferArchiveError("Retained job storage has an unsafe or ambiguous layout.") from error
    prefix = job_archive_key(job_uuid)
    sources, directories, seen = [], [{"root": "work", "key": prefix}], set()

    def retain(path, relative):
        parts = Path(relative).parts
        if native and (any(p.startswith(".qc-tool-") or p in {".staging", ".trash"} for p in parts)
                       or (not path.is_dir() and parts[-1].lower().endswith((".log", ".stdout", ".pre")))):
            return
        key = validate_key(prefix + "/" + relative)
        if key in seen:
            raise TransferArchiveError("Job artifact aliases overlap in the transfer namespace.")
        seen.add(key)
        if path.is_symlink():
            raise TransferArchiveError("A retained job artifact is a symbolic link.")
        if path.is_dir():
            directories.append({"root": "work", "key": key})
            for entry in sorted(os.scandir(path), key=lambda item: item.name):
                retain(Path(entry.path), relative + "/" + entry.name)
        elif path.is_file():
            sources.append(ArtifactSource("work", key, path, root))
        else:
            raise TransferArchiveError("A retained job artifact is a special file.")

    if paths.legacy:
        for entry in sorted(os.scandir(paths.directory), key=lambda item: item.name):
            path = Path(entry.path)
            if entry.name == "output.d":
                retain(path, entry.name)
            elif entry.is_symlink():
                raise TransferArchiveError("A retained job artifact is a symbolic link.")
            elif entry.is_file(follow_symlinks=False):
                if not entry.name.lower().endswith((".log", ".stdout", ".pre")):
                    retain(path, entry.name)
            elif entry.is_dir(follow_symlinks=False):
                if native and entry.name not in {"input.d", "tmp.d"}:
                    retain(path, entry.name)
            else:
                raise TransferArchiveError("A retained job artifact is a special file.")
        return tuple(sources), tuple(directories)

    specification = context["specification"]
    filename = specification["filename"]
    if filename and (paths.specification_path(filename).exists() or not target):
        specimen = paths.specification_path(filename)
        with open_regular(specimen, storage_root=root) as stream:
            checksum, _size = _hash(stream, 16 * 1024**3)
        if checksum != specification["sha256"]:
            raise TransferArchiveError("The retained job recipe differs from its immutable context.")
    for entry in os.scandir(paths.specification_dir) if paths.specification_dir.exists() else ():
        if entry.name != filename:
            raise TransferArchiveError("Canonical specification storage contains an unrecognized artifact.")
    for directory in (paths.specification_dir, paths.reports_dir, paths.output_dir):
        if directory.exists() or directory.is_symlink():
            retain(directory, directory.name)
    for entry in sorted(os.scandir(paths.directory), key=lambda item: item.name):
        if entry.name in {"specification", "reports", "outputs", "logs"}:
            continue
        if entry.name not in {"job.json", "result.json"}:
            raise TransferArchiveError("Canonical job storage contains an unrecognized artifact.")
        retain(Path(entry.path), entry.name)
    return tuple(sources), tuple(directories)
