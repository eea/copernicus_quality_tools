# Database audit: products, units and acceptance

Audited the local PostgreSQL schema read-only on 2026-09-18 and compared it with
Django model ownership, indexes and the publication workflow. The database
contained **25 tables: 16 application tables and 9 Django tables**. Table count
alone is not an optimization target. No existing database was reset or altered.

## Inventory and decisions

The [application schema](SCHEMA.md) lists every application table and its owning
model. All 16 store separate facts and remain necessary:

| Area | Tables | Decision |
| --- | --- | --- |
| Accounts | `account_profile`, `account_api_token`, `account_product_grant`, `account_region_grant` | Retain separate profile, credentials and many-to-many grants. Name geographic permission codes `region_code`. |
| Catalog | `catalog_product`, `catalog_release_revision`, `catalog_definition_revision`, `catalog_release_definition`, `catalog_product_unit` | Separate business identity, approved scope, executable specification, their mapping and required units. Rename `catalog_release_aoi` to `catalog_product_unit` in the draft model. |
| Execution | `execution_delivery`, `execution_job` | A user delivery may have many QC runs; retain both and their provenance. |
| Storage | `storage_delivery_source` | Retain remote source coordinates separately from execution and archived publication files. |
| Publication | `publication_submission`, `publication_conflict`, `publication_conflict_event`, `publication_review_event` | Separate retained receipts, current competition state and append-only decision histories. |

Framework tables are `auth_user`, `auth_group`, `auth_permission`,
`auth_user_groups`, `auth_user_user_permissions`, `auth_group_permissions`,
`django_content_type`, `django_session` and `django_admin_log`. These support
Django authentication, permissions, sessions and audit history. They should not
be consolidated into application tables. Draft schema initialization does not
create an applied migration history; released installations also have Django's
migration recorder.

The largest local table was the required-unit catalog: approximately 126,726
rows and 23 MB including indexes. Definition JSON documents occupied about
2.2 MB across 830 revisions. These are observed estimates, not production
capacity measurements. There is no evidence here that partitioning, flattening
JSON configuration or removing history would improve this workload.

## Terminology and workflow

1. An administrator uploads a JSON product specification. The product keeps a
   stable identity while executable definitions and release scopes are versioned.
2. A release declares required `ProductUnit` records, identified by
   `product_unit_code`. Explicit `product_units` in a specification supports
   units beyond geographic areas. Legacy geographic naming parameters are
   adapted at the import boundary.
3. Assigned users submit deliveries and run QC. QC verifies one unit against the
   snapshotted specification. Users then submit the retained result for review.
4. A product manager accepts a delivery for a required unit. Coverage counts
   distinct units with a published, accepted candidate, not uploads or QC runs.
5. When every current release has an authoritative, nonempty scope and every
   required unit is accepted, a manager can explicitly mark the product ready.
   Complete coverage alone does not mark it ready. A changed scope, relevant
   acceptance decision or product archive invalidates the final approval.

The product readiness service evaluates all current release streams; paginated
UI limits and rounded percentages cannot authorize completion. Product grants
remain reusable for default users and managers. Unit metadata does not confer
product or geographic authorization.

## Integrity and indexing

A conditional unique constraint permits at most one published, accepted
submission per unit. Multiple pending, rejected and historical candidates remain
valid. Replacement declines the incumbent before accepting its replacement,
within the same transaction. State checks and nonnegative-size checks catch
invalid direct writes as well as ordinary form input.

The audit found redundant single-column foreign-key indexes alongside B-tree
indexes beginning with the same column. The draft models suppress these
redundant indexes for:

- Token, product-grant and region-grant owners.
- Release product, unit release and release-definition release references.
- Job delivery references, already covered by the deterministic latest-job index.
- Submission unit and release references, already covered by publication filters.
- Review-event submission and conflict-event conflict references.

PostgreSQL introspection confirmed **105 indexes in the original local schema
and 96 in the fresh schema**. Eleven redundant indexes were removed; the new
accepted-candidate uniqueness constraint and readiness actor foreign key add
two. Both schemas contain 25 tables. The fresh schema has no business columns
using `aoi` terminology.

Retain the composite unique constraints, reverse unit-code lookup, queue index,
other foreign-key indexes and receipt uniqueness. Each removed index otherwise
adds storage and maintenance on writes. Backend introspection tests verify that
those access paths still exist; this is not a claimed latency benchmark.

No speculative JSONB GIN, text-search, partitioning or archival changes were
introduced. Further tuning should use production query frequencies and plans
rather than the small local execution dataset.

## Development and compatibility

The policy remains `draft`; no first-party migration or baseline is added.
Validate with the application-wide database workflow on fresh disposable SQLite
and PostgreSQL databases. An existing draft schema cannot be upgraded by
`database apply`: use a fresh development target and preserve old data for a
separately reviewed conversion. Do not point this code at the old schema and
expect field renames to occur automatically.

Public application fields and filters use product-unit terminology. Raw legacy
worker metadata is accepted through explicit adapters. New publication manifests
use version 2; version 1 verification retains the original keys and checksum.
Geographic AOI checks and their executable JSON parameters retain their actual
geographic meaning. See [product-unit metadata](../../../docs/architecture/product-unit-metadata.md).

## Verification

- Fresh PostgreSQL 14 and SQLite schemas passed the whole-app schema probe,
  named index/constraint checks, synthetic relationships, role bootstrap and
  repeated initialization.
- Full backend runs exercised 868 tests per database. Remaining vocabulary and
  legacy-input fixture assertions were corrected; all 61 affected tests passed
  in follow-up runs on both backends. SQLite skips PostgreSQL-only concurrency
  cases; those execute on PostgreSQL.
- All 21 worker/identifier tests and 93 JavaScript tests passed.
- All 21 database-history policy tests passed; no migration definitions or
  baseline snapshots were created.
- Readiness tests include permissions, CSRF/method restrictions, stale forms,
  reversed/replaced acceptance, restored earlier scopes and a 35,001-unit plan
  evaluated with one aggregate query.

Verification used disposable targets only. The audited existing local database
retains its original data and schema.
