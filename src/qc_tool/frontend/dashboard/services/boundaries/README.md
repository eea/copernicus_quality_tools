# Boundary services

The package keeps HTTP concerns outside the boundary-domain workflow. Callers
should import the stable operations and typed failures from `boundaries` rather
than reaching into implementation modules.

- `service.py` orchestrates one locked validate/publish/activate operation.
- `archive/` owns bounded copying, ZIP metadata validation, and safe extraction.
- `storage/` owns trusted-root checks, locking, immutable generation publication,
  atomic activation, compatibility links, and durability helpers.
- `legacy.py` performs the fail-closed migration from direct raster/vector paths.
- `resolver.py` pins readers to one active immutable generation.
- `catalog.py` lists files from a pinned generation with explicit limits.
- `contracts.py`, `errors.py`, and `layout.py` hold shared domain types and policy.

`archive/__init__.py` and `storage/__init__.py` are compatibility facades. Keep
their exported imports stable when implementation files are reorganized.
