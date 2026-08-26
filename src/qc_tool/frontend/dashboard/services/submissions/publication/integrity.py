"""No-follow verification of files named by a publication manifest."""

import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat

from qc_tool.common import JOB_INPUT_DIRNAME
from qc_tool.common import JOB_OUTPUT_DIRNAME


MAX_MANIFEST_FILES = 20_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PublicationIntegrityError(ValueError):
    """The durable publication tree differs from its signed inventory."""


def verify_publication_inventory(
    root,
    manifest,
    *,
    manifest_filename,
    required_paths=(),
):
    """Verify every regular file and reject links or unlisted content."""

    expected = _expected_inventory(manifest, manifest_filename)
    if any(path not in expected for path in required_paths):
        raise PublicationIntegrityError
    actual, directories = _actual_inventory(
        Path(root),
        manifest_filename=manifest_filename,
        expected_count=len(expected),
    )
    if actual != expected or JOB_OUTPUT_DIRNAME not in directories:
        raise PublicationIntegrityError
    if (
        manifest.get("storage") == "local"
        and JOB_INPUT_DIRNAME not in directories
    ):
        raise PublicationIntegrityError


def _expected_inventory(manifest, manifest_filename):
    entries = manifest.get("files")
    if (
        not isinstance(entries, list)
        or not entries
        or len(entries) > MAX_MANIFEST_FILES
    ):
        raise PublicationIntegrityError

    inventory = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise PublicationIntegrityError
        path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size")
        if not _valid_relative_path(path) or path == manifest_filename:
            raise PublicationIntegrityError
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise PublicationIntegrityError
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PublicationIntegrityError
        if path in inventory:
            raise PublicationIntegrityError
        inventory[path] = (digest, size)
    return inventory


def _actual_inventory(root, *, manifest_filename, expected_count):
    inventory = {}
    directories = set()
    stack = [(root, PurePosixPath())]
    while stack:
        directory, prefix = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise PublicationIntegrityError from exc
        for entry in entries:
            relative = prefix / entry.name
            relative_text = relative.as_posix()
            if not prefix.parts and entry.name == manifest_filename:
                continue
            if entry.is_symlink():
                raise PublicationIntegrityError
            if entry.is_dir(follow_symlinks=False):
                directories.add(relative_text)
                stack.append((Path(entry.path), relative))
                continue
            if not entry.is_file(follow_symlinks=False):
                raise PublicationIntegrityError
            inventory[relative_text] = _digest_regular_file(entry.path)
            if len(inventory) > expected_count:
                raise PublicationIntegrityError
    return inventory, directories


def _digest_regular_file(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PublicationIntegrityError
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest(), metadata.st_size
    except OSError as exc:
        raise PublicationIntegrityError from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _valid_relative_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return bool(
        not path.is_absolute()
        and path.parts
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
    )
