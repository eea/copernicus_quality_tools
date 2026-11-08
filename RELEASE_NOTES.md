# QC Tool 3.0.0

## Database initialization and supported adoption

The current QC Tool 3.0.0 includes **committed native Django migrations** for the
whole application. `database plan|check` inspect schema and history read-only.
`database apply` initializes an **entirely empty database** from committed history,
including in production; it is a read-only no-op for a complete current managed
schema. Partial or foreign schemas, unknown history and detected model drift are
refused. Startup never upgrades or resets an existing database.

Earlier installations of the same 3.0.0 version may have a history-free,
models-only schema. Only the exact supported complete schema can adopt initial
history, using ready maintenance, a full backup and a separately verified
restored candidate. The serving database and original file paths are retained;
the administrator explicitly selects the verified copy before reopening.
Future 3.0.1 and 3.1.0 releases preserve these migration identities and add
reviewed forward migrations. Version labels alone do not prove compatibility.

Legacy records are converted manually outside the codebase into a separate
prepared database copy. Restore only a validated current-schema artifact using
the [manual restore guide](src/qc_tool/database/MANUAL_RESTORE.md). Missing ZIPs,
reports, credentials and publication folders cannot be recreated by restoring
database rows; historical dates do not become verified receipts or approvals.

## What changes

- Explicit product assignments control default-user and product-manager access.
  Obsolete country/region authorization is removed.
- Administrators upload original JSON specifications to create catalog products.
  Startup leaves the catalog empty and specifications are never rewritten.
- Product plans identify required product units. Every required unit needs an
  accepted delivery, followed by final manager confirmation before readiness.
- Submission review lives under Products and supports bulk approval. Product
  queues show pending review work with permission-aware navigation.
- Delivery filename identification integrates the pinned parsEO development
  revision through QC Tool configuration outside product specifications.
- Product, delivery, QC-result and review pages have clearer actions and shared
  table controls, notifications and consistent workspace navigation.
- API token access snapshots, credential-file references and publication history
  preserve explicit access boundaries and review provenance.
- **Admin → Maintenance → Database migrations** shows schema/history readiness,
  applied and pending changes, backup coverage, preparation progress and reviewed
  database selection. SQL migrations preserve original specifications, delivery
  ZIPs, QC artifacts and publications at their existing physical paths.

## Operator actions

Review user/product assignments after import, issue replacement API and S3
credentials, and upload the original product specification files. Removed routes
and country/region fields are not compatibility aliases; update integrations to
the documented API, including `verified_product_unit_code`.

Production can initialize an entirely empty database through the same native
migration command. Use the guarded candidate workflow for supported adoption or
upgrades. Run schema, history, data, access and storage checks before selecting a
prepared copy; do not attach a legacy database and expect startup to convert it.
`QC_TOOL_INITIALIZE_ON_STARTUP=yes` is reserved for development/test convenience.

Use a verified frontend/worker image pair from the same release. Image publication
and deployment remain pending; do not substitute an earlier worker without
release-specific compatibility evidence. The current candidate is **not yet
published or approved for production deployment**.

See the [release record](src/qc_tool/database/releases/3.0.0.md),
[schema dictionary](src/qc_tool/database/TABLES.md), and
[database guide](src/qc_tool/database/README.md).
