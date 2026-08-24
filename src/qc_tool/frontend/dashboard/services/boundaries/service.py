"""Boundary-package activation orchestration."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
import tempfile
from typing import BinaryIO, Optional, Union
import zlib
from zipfile import BadZipFile, LargeZipFile, ZipFile

from .archive import copy_archive_bounded, extract_archive, validate_archive
from .contracts import BoundaryPackageLimits, BoundaryPackageResult
from .errors import (
    BoundaryPackageError,
    BoundaryPackageInternalError,
    BoundaryPackageInvalid,
    BoundaryPackagePromotionError,
)
from .layout import new_generation_id
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

    root = prepare_boundary_root(boundary_dir)
    try:
        with boundary_package_lock(root, timeout=lock_timeout):
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
        logger.exception("Boundary package activation failed because of a filesystem error")
        raise BoundaryPackagePromotionError("unexpected filesystem failure") from exc
    except Exception as exc:
        logger.exception("Unexpected boundary package processing failure")
        raise BoundaryPackageInternalError("unexpected processing failure") from exc
