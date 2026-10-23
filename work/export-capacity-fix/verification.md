# Portable export capacity correction

23 October 2026. Changes are limited to central database transfer logic,
configuration, Admin review presentation, tests and documentation. No model,
schema, migration, specification, vector or raster change is required.

## Verified cause

Read-only SQL counts on the local current-model installation found 130,238
product-unit rows and 133,672 records in the connected export selection,
including its exact account dependencies. The previous 100,000-record default
made a normal complete catalog impossible to export as an additive package.
The previous message recommended an offline procedure despite an existing
native PostgreSQL backup workflow in Admin.

## Correction

- Portable default capacity is 250,000 records. The existing configurable
  1–1,000,000 range, archive/JSON byte limits and strict graph/schema validation
  remain. Nothing is truncated or silently converted to another profile.
- SQL capacity checks precede record serialization and file inspection. Counts
  and the configured limit appear in review; creation and execution recheck.
  The same account-dependency selector serves counts and serialization.
- Over-limit review has an explicit Admin backup link carrying the selected
  file option. It explains separate-database restore versus additive import.
- Namespace initialization releases the previous snapshot before rebuilding,
  avoiding simultaneous retention of two complete catalogs.
- A 130,238-unit core import plan measured 37.64 MiB with the previous journal
  representation. Known additive journals now retain replay decisions,
  recovery selection and full-plan integrity evidence; they reconstruct and
  verify the complete plan before use. Source records stay in the verified
  package, and committed results stay complete in SQL receipts. Private
  summaries use the same projection as the Admin API. The journal cap remains
  32 MiB; legacy full journals stay readable.
- Internal current-database verification uses stable provenance-ledger bounds,
  independent of the portable upload limit. Uploaded packages remain bounded.

## Evidence

All database/file mutation tests used isolated disposable PostgreSQL 14 or
SQLite targets and temporary storage. No live data was exported, imported,
reset or migrated. The local runtime reports a 250,000-record configured limit.

- Initial PostgreSQL checks: 185 tests passed, zero skips/failures/errors,
  including a real 130,238-unit service export and archive revalidation.
- Expanded large-catalog PostgreSQL check: real export, complete record and
  provenance identity comparison, archive reader validation, staging and a
  durable additive review for 130,237 missing units all passed in 58.785 s.
  This check verifies review at scale; it does not execute a 130,237-row insert.
- Admin transfer presentation: 116 SQLite tests passed.
- Provenance/record contracts: 46 PostgreSQL tests passed.
- Final source-frozen PostgreSQL central database integration and Admin
  transfer/database-route/record-management regression: **521 tests passed**,
  zero failures/errors/skips, in 192.818 s. This includes the expanded large
  catalog test and compact-plan, stale-review, lost-commit acknowledgement,
  rollback and receipt recovery checks. Log:
  `/tmp/qc-transfer-validation-d9a13b6c8f5c.log`.
- Final whitespace check passed; local `/health` returned `{"status":"ok"}`.
  Disposable test PostgreSQL containers were removed after their runs.

Portable records and plans are processed in memory; the larger default is not
an unbounded streaming importer or a throughput guarantee. Operators must size
frontend memory for intended package contents. Native PostgreSQL capture
streams independently of the portable row cap. EEA deployment and Docker Hub
release validation are outside this local verification.
