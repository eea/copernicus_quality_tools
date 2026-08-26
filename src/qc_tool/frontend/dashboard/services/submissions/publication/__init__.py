"""Idempotent, atomic filesystem publication for one reserved submission."""

from qc_tool.common import compose_job_dir
from qc_tool.frontend.dashboard.services.uploads import (
    DeliveryUploadPathError,
)

from ..contracts import PublicationReceipt
from ..contracts import ReservedSubmission
from ..errors import PublicationError
from .delivery_input import copy_delivery_input
from .job_artifacts import copy_job_artifacts
from .layout import discard_owned_staging
from .layout import publication_layout
from .manifest import build_manifest
from .manifest import MANIFEST_FILENAME
from .manifest import receipt_from_existing
from .manifest import SUBMITTED_MARKER
from .secure_copy import inventory_entry
from .secure_copy import write_owned_file


def publish_reserved_submission(
    reserved: ReservedSubmission,
    *,
    submission_root,
    media_root,
):
    """Copy complete artifacts to staging and atomically expose the result."""

    layout = publication_layout(reserved, submission_root=submission_root)
    if layout.final_directory.exists() or layout.final_directory.is_symlink():
        return receipt_from_existing(layout.final_directory, reserved)

    discard_owned_staging(layout)
    try:
        layout.staging_directory.mkdir(mode=0o750)
        file_inventory = []
        copy_job_artifacts(
            reserved,
            compose_job_dir(reserved.job_uuid),
            layout.staging_directory,
            file_inventory,
        )
        input_digest = copy_delivery_input(
            reserved,
            layout.staging_directory,
            media_root=media_root,
            file_inventory=file_inventory,
        )
        _write_marker(
            reserved,
            layout.staging_directory,
            file_inventory,
        )
        manifest_bytes, digest = build_manifest(
            reserved,
            input_digest=input_digest,
            file_inventory=file_inventory,
        )
        write_owned_file(
            layout.staging_directory / MANIFEST_FILENAME,
            manifest_bytes,
        )

        recovered = _expose_staging(layout, reserved)
        if recovered is not None:
            return recovered
        return PublicationReceipt(
            artifact_path=str(layout.final_directory),
            artifact_digest=digest,
            input_digest=input_digest,
        )
    except PublicationError:
        discard_owned_staging(layout)
        raise
    except DeliveryUploadPathError as exc:
        discard_owned_staging(layout)
        raise PublicationError(exc.code, exc.message, exc.status_code) from exc
    except (OSError, ValueError, TypeError) as exc:
        discard_owned_staging(layout)
        raise PublicationError(
            "artifact_publication_failed",
            "The validated delivery artifacts could not be published.",
            500,
        ) from exc


def _write_marker(reserved, staging_directory, file_inventory):
    marker = (reserved.requested_at_iso + "\n").encode("utf-8")
    write_owned_file(staging_directory / SUBMITTED_MARKER, marker)
    file_inventory.append(inventory_entry(SUBMITTED_MARKER, marker))


def _expose_staging(layout, reserved):
    try:
        layout.staging_directory.rename(layout.final_directory)
    except OSError:
        # Another process can only win with the same deterministic UUID.
        # Validate its durable manifest; never overwrite it.
        if layout.final_directory.exists() or layout.final_directory.is_symlink():
            discard_owned_staging(layout)
            return receipt_from_existing(layout.final_directory, reserved)
        raise
    return None
