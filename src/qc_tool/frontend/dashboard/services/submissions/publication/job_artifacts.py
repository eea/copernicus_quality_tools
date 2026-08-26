"""Validation and copying of publishable worker output artifacts."""

import os
from pathlib import Path

from qc_tool.common import JOB_OUTPUT_DIRNAME

from ..errors import PublicationError
from .manifest import MANIFEST_FILENAME
from .manifest import SUBMITTED_MARKER
from .secure_copy import copy_regular_file


def copy_job_artifacts(_reserved, source, destination, inventory):
    if source.is_symlink() or not source.is_dir():
        raise PublicationError(
            "job_artifacts_unavailable",
            "The successful QC job artifacts are unavailable.",
            409,
        )
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
