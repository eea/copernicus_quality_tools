"""Compatibility exports; shared boundary contracts live in ``qc_tool.boundaries``."""

from qc_tool.boundaries.layout import (
    GENERATIONS_DIRECTORY_NAME,
    TRASH_DIRECTORY_NAME,
    CURRENT_POINTER_NAME,
    LEGACY_BACKUPS_DIRECTORY_NAME,
    new_generation_id,
    validate_generation_id,
    generations_dir,
    generation_dir,
    current_pointer,
    current_pointer_target,
    compatibility_link_target,
    legacy_backups_dir,
    path_lexists,
)

__all__ = (
    "GENERATIONS_DIRECTORY_NAME",
    "TRASH_DIRECTORY_NAME",
    "CURRENT_POINTER_NAME",
    "LEGACY_BACKUPS_DIRECTORY_NAME",
    "new_generation_id",
    "validate_generation_id",
    "generations_dir",
    "generation_dir",
    "current_pointer",
    "current_pointer_target",
    "compatibility_link_target",
    "legacy_backups_dir",
    "path_lexists",
)
