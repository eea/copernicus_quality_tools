# QC Tool 3.0.0

## Major release: fresh database required

QC Tool 3.0.0 uses a **models-only schema**, with no migration framework,
first-party definitions, initial snapshots or legacy converter. The
whole-application `database plan|check` commands inspect the schema read-only.
`database apply` initializes an **entirely empty database** from current models,
including in production; it is a read-only no-op for a complete matching schema.
Partial or foreign schemas and detected model drift are refused. Initialization
never upgrades or resets an existing database.

The first migration-managed schema is reserved for an explicitly reviewed
release from **3.0.1 onward**. Existing 3.0.0 tables cannot automatically adopt
new initial migrations; a separate conversion/adoption plan is required. Never
use fake migration records to bypass that transition.

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

## Operator actions

Review user/product assignments after import, issue replacement API and S3
credentials, and upload the original product specification files. Removed routes
and country/region fields are not compatibility aliases; update integrations to
the documented API, including `verified_product_unit_code`.

Production can initialize an entirely empty database through the same models-only
command. Run schema and data checks on a prepared restore before selecting it for
cutover; do not attach a legacy database and expect startup to convert it.
`QC_TOOL_INITIALIZE_ON_STARTUP=yes` is reserved for development/test convenience.

Use a verified frontend/worker image pair from the same release. Image publication
and deployment remain pending; do not substitute an earlier worker without
release-specific compatibility evidence. The current candidate is **not yet
published or approved for production deployment**.

See the [release record](src/qc_tool/database/releases/3.0.0.md),
[schema dictionary](src/qc_tool/database/TABLES.md), and
[database guide](src/qc_tool/database/README.md).
