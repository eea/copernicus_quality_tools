"""Validation and copying of publishable worker output artifacts."""

import os
from pathlib import Path

from qc_tool.common import JOB_OUTPUT_DIRNAME
from qc_tool.jobs import JobStorageError, read_job_context, resolve_job_paths

from ..errors import PublicationError
from .manifest import MANIFEST_FILENAME
from .manifest import SUBMITTED_MARKER
from .secure_copy import copy_regular_file


def copy_job_artifacts(reserved, source, destination, inventory):
    if source.is_symlink() or not source.is_dir():
        raise PublicationError(
            "job_artifacts_unavailable",
            "The successful QC job artifacts are unavailable.",
            409,
        )
    try:
        paths = resolve_job_paths(source.parent, reserved.job_uuid, require_exists=True)
        if paths.directory != source:
            raise JobStorageError("Job artifact source differs from its resolved identity.")
    except JobStorageError as exc:
        raise PublicationError("job_artifacts_unavailable", "The successful QC job artifact layout could not be verified.", 409) from exc
    if not paths.legacy:
        _copy_canonical_artifacts(reserved, paths, destination, inventory)
        return
    for entry in sorted(os.scandir(source), key=lambda item: item.name):
        if entry.is_symlink():
            raise PublicationError(
                "unsafe_job_artifact",
                "QC job artifacts contain a symbolic link.",
                409,
            )
        if entry.is_file(follow_symlinks=False):
            _copy_top_level_file(entry, destination, inventory)
        elif entry.is_dir(follow_symlinks=False):
            if entry.name == JOB_OUTPUT_DIRNAME:
                output_destination = destination / JOB_OUTPUT_DIRNAME
                output_destination.mkdir(mode=0o750)
                _copy_tree(
                    Path(entry.path),
                    output_destination,
                    prefix=JOB_OUTPUT_DIRNAME,
                    inventory=inventory,
                )
            # Worker scratch/input directories are not publication artifacts.
        else:
            raise PublicationError(
                "unsafe_job_artifact",
                "QC job artifacts contain an unsupported filesystem object.",
                409,
            )
    if not (destination / JOB_OUTPUT_DIRNAME).is_dir():
        raise PublicationError(
            "job_output_unavailable",
            "The successful QC job output directory is unavailable.",
            409,
        )


def _copy_canonical_artifacts(reserved, paths, destination, inventory):
    context = read_job_context(paths)
    specification = context["specification"]
    if not specification["filename"] or specification["sha256"] != reserved.definition_digest:
        raise PublicationError(
            "job_specification_mismatch",
            "The retained job specification does not match its recorded catalog version.", 409,
        )
    for source in (paths.metadata_path, paths.result_path):
        digest, size = copy_regular_file(source, destination / source.name)
        inventory.append({"path": source.name, "sha256": digest, "size": size})
    for source in (paths.specification_dir, paths.reports_dir, paths.output_dir):
        if not source.is_dir():
            raise PublicationError("job_artifacts_unavailable", "The successful QC job artifacts are incomplete.", 409)
        target = destination / source.name
        target.mkdir(mode=0o750)
        _copy_tree(source, target, prefix=source.name, inventory=inventory)
    retained_spec = next((item for item in inventory if item["path"] == (
        "specification/" + specification["filename"]
    )), None)
    if retained_spec is None or retained_spec["sha256"] != specification["sha256"]:
        raise PublicationError(
            "job_specification_mismatch", "The retained job specification failed its integrity check.", 409,
        )


def _copy_top_level_file(entry, destination, inventory):
    if entry.name in {MANIFEST_FILENAME, SUBMITTED_MARKER}:
        raise PublicationError(
            "unsafe_job_artifact",
            "QC job artifacts use a reserved publication filename.",
            409,
        )
    digest, size = copy_regular_file(
        Path(entry.path),
        destination / entry.name,
    )
    inventory.append({"path": entry.name, "sha256": digest, "size": size})


def _copy_tree(source, destination, *, prefix, inventory):
    for entry in sorted(os.scandir(source), key=lambda item: item.name):
        relative = "{}/{}".format(prefix, entry.name)
        target = destination / entry.name
        if entry.is_symlink():
            raise PublicationError(
                "unsafe_job_artifact",
                "QC job output contains a symbolic link.",
                409,
            )
        if entry.is_dir(follow_symlinks=False):
            target.mkdir(mode=0o750)
            _copy_tree(
                Path(entry.path),
                target,
                prefix=relative,
                inventory=inventory,
            )
        elif entry.is_file(follow_symlinks=False):
            digest, size = copy_regular_file(Path(entry.path), target)
            inventory.append(
                {"path": relative, "sha256": digest, "size": size}
            )
        else:
            raise PublicationError(
                "unsafe_job_artifact",
                "QC job output contains an unsupported filesystem object.",
                409,
            )
