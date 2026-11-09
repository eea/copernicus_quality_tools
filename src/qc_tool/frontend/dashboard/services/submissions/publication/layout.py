"""Choose a versioned publication location while retaining historical keys."""

from ..contracts import PublicationLayout
from ..errors import PublicationError
from ..storage import artifact_directory
from .directories import ensure_publication_directories, publication_root
from .path_identity import legacy_publication_components, publication_components


def publication_layout(reserved, *, submission_root):
    root = publication_root(submission_root)
    name = "submission-{}.d".format(reserved.submission_uuid)
    legacy = tuple(root.joinpath(*parts, name) for parts in legacy_publication_components(reserved))
    recorded_key = reserved.artifact_key
    if recorded_key:
        try:
            recorded = artifact_directory(root, recorded_key, require_exists=False)
        except (OSError, ValueError, RuntimeError) as exc:
            raise PublicationError("publication_path_conflict", "The stored publication key is unsafe.", 409) from exc
        if recorded in legacy:
            final = recorded
        elif reserved.original_publication_identity is not None:
            # A reviewed additive import can translate local integer IDs.
            # Its immutable key and original manifest remain authoritative.
            try:
                final = artifact_directory(root, recorded_key)
            except (OSError, ValueError, RuntimeError) as exc:
                raise PublicationError("publication_path_conflict", "The imported publication location is unavailable.", 409) from exc
        else:
            current = root.joinpath(*publication_components(reserved), name)
            if recorded != current:
                raise PublicationError("publication_path_conflict", "The stored publication path does not match this submission.", 409)
            final = recorded
    else:
        # A previous atomic rename can precede its database receipt. Recover
        # its original layout; the manifest is verified before finalization.
        existing = [path for path in legacy if path.exists() or path.is_symlink()]
        if len(existing) > 1:
            raise PublicationError("publication_path_conflict", "Multiple historical locations exist for this submission.", 409)
        final = existing[0] if existing else root.joinpath(*publication_components(reserved), name)
    parent = ensure_publication_directories(root, *final.parent.relative_to(root).parts)
    return PublicationLayout(
        root=root, final_directory=parent / name,
        staging_directory=parent / ".submission-{}.pending".format(reserved.submission_uuid),
    )
