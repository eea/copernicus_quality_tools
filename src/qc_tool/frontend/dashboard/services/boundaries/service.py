"""Boundary-package activation orchestration."""

from __future__ import annotations

import errno
import logging
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import BinaryIO, Optional, Union
import zlib
from zipfile import BadZipFile, LargeZipFile, ZipFile

from .archive import copy_archive_bounded, extract_archive, validate_archive
from .archive.copying import check_archive_size, declared_archive_size
from .contracts import BoundaryPackageLimits, BoundaryPackageResult, LIVE_DIRECTORY_NAMES
from .errors import (
    BoundaryPackageConfigurationError,
    BoundaryPackageError,
    BoundaryPackageInsufficientSpace,
    BoundaryPackageInternalError,
    BoundaryPackageInvalid,
    BoundaryPackagePromotionError,
)
from .layout import current_pointer, new_generation_id, path_lexists
from .legacy import ensure_compatibility_layout
from .resolver import resolve_boundary_generation
from .storage import (
    activate_generation,
    boundary_package_lock,
    prepare_boundary_root,
    publish_generation,
    remove_tree,
)


logger = logging.getLogger(__name__)
_MINIMUM_FREE_HEADROOM = 256 * 1024**2
_MAX_CAPACITY_SCAN_ENTRIES = 100_000


def inspect_boundary_capacity(boundary_dir) -> dict[str, int]:
    """Report configured storage capacity without creating or changing files."""
    try:
        root = Path(boundary_dir)
    except (TypeError, ValueError) as error:
        raise BoundaryPackageConfigurationError("boundary capacity root is invalid") from error
    try:
        if not root.is_absolute() or ".." in root.parts or root == Path(root.anchor):
            raise BoundaryPackageConfigurationError("boundary capacity root is invalid")
        # A fresh installation need not have a boundary directory yet. Inspect
        # its existing ancestor's filesystem without creating the future root.
        existing = root
        while not existing.exists():
            if existing.is_symlink():
                raise BoundaryPackageConfigurationError("boundary capacity path is unsafe")
            existing = existing.parent
        for component in (existing, *existing.parents):
            if component.is_symlink() or not component.is_dir():
                raise BoundaryPackageConfigurationError("boundary capacity path is unsafe")
        usage = shutil.disk_usage(existing)
        return {"free_bytes": usage.free, "total_bytes": usage.total, "used_bytes": usage.used}
    except OSError as error:
        raise BoundaryPackageConfigurationError("boundary capacity cannot be inspected") from error


def _required_free_bytes(payload_bytes: int) -> int:
    # Current disk.free already excludes the upload spool, staged archive and
    # existing generations. Reserve room for new bytes plus metadata/other I/O.
    return payload_bytes + max(_MINIMUM_FREE_HEADROOM, (payload_bytes + 19) // 20)


def _require_capacity(directory: Path, payload_bytes: int) -> None:
    available = inspect_boundary_capacity(directory)["free_bytes"]
    required = _required_free_bytes(payload_bytes)
    if available < required:
        raise BoundaryPackageInsufficientSpace(required_bytes=required, available_bytes=available)


def _legacy_snapshot_bytes(root: Path) -> int:
    """Count a required first-activation copy without following legacy links."""
    if path_lexists(current_pointer(root)):
        # An existing managed/partly adopted generation will not be copied by
        # ensure_compatibility_layout; its bytes are already in disk.used.
        return 0
    pending = []
    for name in LIVE_DIRECTORY_NAMES:
        source = root / name
        if source.is_symlink():
            raise BoundaryPackageConfigurationError("legacy boundary path is unsafe")
        if source.exists():
            if not source.is_dir():
                raise BoundaryPackageConfigurationError("legacy boundary path is unsafe")
            pending.append(source)
    total = scanned = 0
    try:
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    scanned += 1
                    if scanned > _MAX_CAPACITY_SCAN_ENTRIES:
                        raise BoundaryPackageConfigurationError("legacy capacity scan exceeds its safety bound")
                    status = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(status.st_mode):
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(status.st_mode):
                        total += status.st_size
                    else:
                        raise BoundaryPackageConfigurationError("legacy boundary tree contains an unsafe entry")
    except OSError as error:
        raise BoundaryPackageConfigurationError("legacy boundary capacity cannot be inspected") from error
    return total


def replace_boundary_package(
    archive: Union[BinaryIO, str, os.PathLike],
    boundary_dir: Union[str, os.PathLike],
    *,
    limits: Optional[BoundaryPackageLimits] = None,
    lock_timeout: float = 30.0,
) -> BoundaryPackageResult:
    """Validate, extract, and replace a boundary package with locked rollback.

    ``archive`` may be a Django ``UploadedFile``, any readable binary file
    object, or a filesystem path. Uploaded bytes exist only in a private
    staging directory and are removed after success or failure; no user-chosen
    filename is ever written to the boundary directory.

    The archive must contain regular files below ``raster/`` and/or ``vector/``.
    Domain-specific AOI and geospatial content validation remains a later step.
    """

    effective_limits = limits or BoundaryPackageLimits()
    if (
        isinstance(lock_timeout, bool)
        or not isinstance(lock_timeout, (int, float))
        or not math.isfinite(lock_timeout)
        or lock_timeout < 0
    ):
        raise ValueError("lock_timeout must be finite and cannot be negative")

    # UploadedFile.size is available before any service-owned staging copy.
    # The copy still enforces its byte bound against understated/changing input.
    check_archive_size(archive, effective_limits.max_archive_bytes)
    declared_size = declared_archive_size(archive)
    root = prepare_boundary_root(boundary_dir)
    activation_attempted = False
    try:
        with boundary_package_lock(root, timeout=lock_timeout):
            if declared_size is not None:
                _require_capacity(root, declared_size)
            staging_dir = Path(tempfile.mkdtemp(prefix=".boundary-staging-", dir=root))
            try:
                os.chmod(staging_dir, 0o700)
                staged_archive = staging_dir / "upload.zip"
                payload_dir = staging_dir / "payload"
                archive_size, digest = copy_archive_bounded(
                    archive,
                    staged_archive,
                    effective_limits.max_archive_bytes,
                )
                try:
                    with ZipFile(staged_archive, mode="r", allowZip64=True) as zip_file:
                        validated = validate_archive(zip_file, effective_limits)
                        _require_capacity(staging_dir, validated.uncompressed_size + _legacy_snapshot_bytes(root))
                        extract_archive(zip_file, validated, payload_dir, effective_limits)
                except (
                    BadZipFile,
                    LargeZipFile,
                    EOFError,
                    RuntimeError,
                    UnicodeError,
                    ValueError,
                    zlib.error,
                ) as exc:
                    raise BoundaryPackageInvalid(
                        "ZIP parsing or integrity validation failed"
                    ) from exc

                generation_id = new_generation_id()
                publish_generation(root, payload_dir, generation_id)

                migration_staging_dir = staging_dir / "legacy-migration"
                migration_staging_dir.mkdir(mode=0o700)
                ensure_compatibility_layout(root, migration_staging_dir)
                activation_attempted = True
                activate_generation(root, generation_id)
                active_generation = resolve_boundary_generation(
                    root,
                    allow_legacy=False,
                )
            finally:
                remove_tree(staging_dir)

        result = BoundaryPackageResult(
            sha256=digest,
            archive_size=archive_size,
            member_count=validated.member_count,
            file_count=validated.file_count,
            uncompressed_size=validated.uncompressed_size,
            generation_id=active_generation.generation_id,
        )
        logger.info(
            "Boundary package activated: generation=%s sha256=%s archive_bytes=%d files=%d "
            "uncompressed_bytes=%d",
            result.generation_id,
            result.sha256,
            result.archive_size,
            result.file_count,
            result.uncompressed_size,
        )
        return result
    except BoundaryPackageError as exc:
        logger.warning("Boundary package activation rejected: code=%s", exc.code)
        raise
    except OSError as exc:
        if not activation_attempted and exc.errno in {errno.ENOSPC, errno.EDQUOT}:
            raise BoundaryPackageInsufficientSpace() from exc
        logger.exception("Boundary package activation failed because of a filesystem error")
        raise BoundaryPackagePromotionError("unexpected filesystem failure") from exc
    except Exception as exc:
        logger.exception("Unexpected boundary package processing failure")
        raise BoundaryPackageInternalError("unexpected processing failure") from exc
