# QC Tool 3.0.0

## Major release: fresh database required

QC Tool 3.0.0 freezes the application schema and introduces committed initial
migrations. Create a **new database** with the whole-application
`database plan|apply|check` workflow. This release does not upgrade a legacy or
model-created development database in place. Never use `--fake` to bypass this
requirement.

To preserve records from the supported 20260907 SQL backup, use the separate
[legacy importer](src/qc_tool/database/LEGACY_IMPORT.md) after initializing the
new target. Users, deliveries, QC jobs, source locations and historical submission
dates can be recovered. Missing ZIPs/reports/publication folders cannot be
recreated; historical dates do not become verified receipts or approvals.

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

Use a verified frontend/worker image pair from the same release. Image publication
and deployment remain pending; do not substitute an earlier worker without
release-specific compatibility evidence. The current candidate is **not yet
published or approved for production deployment**.

See the [release record](src/qc_tool/database/releases/3.0.0.md),
[schema dictionary](src/qc_tool/database/TABLES.md), and
[migration runbook](src/qc_tool/database/MIGRATIONS.md).
