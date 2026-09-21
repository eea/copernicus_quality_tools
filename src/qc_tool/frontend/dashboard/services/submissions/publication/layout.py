"""Deterministic, containment-checked submission storage paths."""

from pathlib import Path
import re
import shutil

from ..contracts import PublicationLayout
from ..errors import PublicationError
from ..storage import artifact_directory
from .secure_copy import sync_directory


_SAFE_COMPONENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def publication_layout(reserved, *, submission_root):
    root = Path(submission_root)
    if root.exists() and root.is_symlink():
        raise PublicationError(
            "unsafe_submission_storage",
            "The submission storage root is not safe.",
            500,
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        sync_directory(root.parent)
    except (OSError, RuntimeError) as exc:
        raise PublicationError(
            "submission_storage_unavailable",
            "The submission storage root is unavailable.",
            503,
        ) from exc
    if not root.is_dir():
        raise PublicationError(
            "submission_storage_unavailable",
            "The submission storage root is unavailable.",
            503,
        )

    release_component = "release-{}-{}".format(
        reserved.product_release_id,
        _safe_component(reserved.release_key),
    )
    unit_component = "product-unit-{}-{}".format(
        reserved.product_unit_id,
        _safe_component(reserved.product_unit_code),
    )
    identifier = str(reserved.submission_uuid)
    final_name = "submission-{}.d".format(identifier)
    legacy_component = "aoi-{}-{}".format(reserved.product_unit_id, _safe_component(reserved.product_unit_code))
    legacy_final = root / release_component / legacy_component / final_name
    current_final = root / release_component / unit_component / final_name
    recorded_key = getattr(reserved, "artifact_key", "")
    if recorded_key:
        try:
            recorded = artifact_directory(root, recorded_key, require_exists=False)
        except (OSError, ValueError, RuntimeError) as exc:
            raise PublicationError("publication_path_conflict", "The stored publication key is unsafe.", 409) from exc
        if recorded not in (legacy_final, current_final):
            raise PublicationError("publication_path_conflict", "The stored publication path does not match this submission.", 409)
        if recorded == legacy_final:
            unit_component = legacy_component
    elif legacy_final.exists() or legacy_final.is_symlink():
        # Recover an old atomic rename whose database receipt was interrupted.
        # Its exact versioned manifest is checked before it can be adopted.
        unit_component = legacy_component
    parent = _ensure_owned_directories(root, release_component, unit_component)
    return PublicationLayout(
        root=root,
        final_directory=parent / final_name,
        staging_directory=parent / ".submission-{}.pending".format(identifier),
    )


def discard_owned_staging(layout):
    """Remove only the deterministic staging directory owned by a submission."""

    staging = layout.staging_directory
    if not staging.exists() and not staging.is_symlink():
        return
    if staging.parent != layout.final_directory.parent or staging.is_symlink():
        raise PublicationError(
            "unsafe_submission_storage",
            "The submission staging path is unsafe.",
            500,
        )
    if not staging.is_dir():
        raise PublicationError(
            "unsafe_submission_storage",
            "The submission staging path is not a directory.",
            500,
        )
    shutil.rmtree(staging)


def _ensure_owned_directories(root, *components):
    current = root
    for component in components:
        candidate = current / component
        try:
            if candidate.is_symlink():
                raise PublicationError(
                    "unsafe_submission_storage",
                    "The submission storage contains an unsafe link.",
                    500,
                )
            candidate.mkdir(mode=0o750, exist_ok=True)
            sync_directory(current)
            resolved = candidate.resolve(strict=True)
        except PublicationError:
            raise
        except (OSError, RuntimeError) as exc:
            raise PublicationError(
                "submission_storage_unavailable",
                "The submission storage is unavailable.",
                503,
            ) from exc
        if resolved.parent != current:
            raise PublicationError(
                "unsafe_submission_storage",
                "The submission storage path escaped its configured root.",
                500,
            )
        current = resolved
    return current


def _safe_component(value):
    text = _SAFE_COMPONENT_RE.sub("-", str(value)).strip(".-_").lower()
    if not text:
        text = "value"
    return text[:80]
