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
- `configuration.py` adapts validated deployment settings into the typed limits
  passed by HTTP callers; it does not change the framework-independent service API.
- `contracts.py`, `errors.py`, and `layout.py` hold shared domain types and policy.

`archive/__init__.py` and `storage/__init__.py` are compatibility facades. Keep
their exported imports stable when implementation files are reorganized.

## Deployment limits

`BoundaryPackageLimits` is the single source of defaults: 4 GiB compressed ZIP,
4 GiB per member, 32 GiB expanded content, 10,000 entries, compression ratio 100,
path length 1,024 bytes, component size 255 bytes and depth 32. These bounds support
large geospatial boundary datasets while retaining archive and path checks.

Django settings builds `QC_TOOL_BOUNDARY_PACKAGE_LIMITS` from the eight
`QC_TOOL_BOUNDARY_MAX_*` environment variables documented in
[the environment reference](../../../../../../docs/reference/environment-variables.md#boundary-package-limits).
Malformed environment values refuse settings loading. Applications using a
custom Django settings module may instead supply a mapping with the exact
`BoundaryPackageLimits` field names and typed integer/float values. Unknown
fields or invalid values fail closed rather than reverting to a default.

HTTP integrations call `configuration.get_boundary_package_limits()` and pass
the returned object as `limits=` to `replace_boundary_package`. The adapter
validates through `BoundaryPackageLimits.from_mapping` on each call; it does
not cache mutable deployment settings. Invalid mappings raise the typed
`BoundaryPackageConfigurationError`. Standalone service callers can continue
to pass an explicit `BoundaryPackageLimits`, or use the same domain defaults.
Do not introduce size overrides in individual views.

All size limits apply together. Increasing the archive limit does not increase
the largest-file or expanded-content limits. Provision temporary upload storage
and boundary staging for the compressed ZIP plus extracted files, retaining
enough additional space for existing generations and any legacy snapshot.
For the inspected approximately 2.4 GiB geospatial ZIP, the Django upload spool,
staged archive and expanded content together need roughly 27 GiB (29 GB), before
retained generations or a legacy snapshot. That is a sizing example, not the
maximum required by every permitted package. Account for additional proxy upload
copies on their respective filesystems and set request/proxy timeouts for the
expected upload, extraction and activation duration.
