"""Map stable archive identities onto deployment-owned physical storage roots.

The ``work/product_definitions`` archive namespace predates separated mounts.
Keep that external identity unchanged; resolve its bytes against the dedicated
specification mount when configured. No filesystem lookup or fallback search is
used for specification aliases. Job aliases use the explicit versioned job
resolver; restore plans pin their choice before publication.
"""

from pathlib import Path


def storage_location(roots, name, key):
    parts = Path(key).parts
    if name == "work" and parts and parts[0] == "product_definitions" and "specifications" in roots:
        return Path(roots["specifications"]), Path(*parts[1:]).as_posix() if len(parts) > 1 else ""
    if name == "work":
        from .job_locations import job_storage_key
        key = job_storage_key(roots, key)
    return Path(roots[name]), key


def storage_path(roots, name, key):
    root, relative = storage_location(roots, name, key)
    return root / relative
