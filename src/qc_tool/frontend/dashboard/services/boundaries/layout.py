"""Names and validation rules for immutable boundary generations."""

from __future__ import annotations

import os
from pathlib import Path
import re
import uuid

from .contracts import LIVE_DIRECTORY_NAMES
from .errors import BoundaryPackageConfigurationError


GENERATIONS_DIRECTORY_NAME = ".boundary-generations"
CURRENT_POINTER_NAME = ".boundary-current"
LEGACY_BACKUPS_DIRECTORY_NAME = ".boundary-legacy-backups"

_GENERATION_ID_PATTERN = re.compile(r"^(?:gen|legacy)-[0-9a-f]{32}$")


def new_generation_id(*, legacy: bool = False) -> str:
    prefix = "legacy" if legacy else "gen"
    return f"{prefix}-{uuid.uuid4().hex}"


def validate_generation_id(generation_id: str) -> str:
    if _GENERATION_ID_PATTERN.fullmatch(generation_id) is None:
        raise BoundaryPackageConfigurationError("boundary generation id is invalid")
    return generation_id


def generations_dir(root: Path) -> Path:
    return root / GENERATIONS_DIRECTORY_NAME


def generation_dir(root: Path, generation_id: str) -> Path:
    return generations_dir(root) / validate_generation_id(generation_id)


def current_pointer(root: Path) -> Path:
    return root / CURRENT_POINTER_NAME


def current_pointer_target(generation_id: str) -> str:
    validate_generation_id(generation_id)
    return f"{GENERATIONS_DIRECTORY_NAME}/{generation_id}"


def compatibility_link_target(directory_name: str) -> str:
    if directory_name not in LIVE_DIRECTORY_NAMES:
        raise ValueError("unknown boundary directory")
    return f"{CURRENT_POINTER_NAME}/{directory_name}"


def legacy_backups_dir(root: Path) -> Path:
    return root / LEGACY_BACKUPS_DIRECTORY_NAME


def path_lexists(path: Path) -> bool:
    return os.path.lexists(path)

