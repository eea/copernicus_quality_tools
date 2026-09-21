# Database audit: schema, metadata and retention

The latest column-level review is **2026-09-21**. Start with the
[complete table dictionary](TABLES.md) for all **25 current tables and 204
columns**, including their purposes, PostgreSQL types, defaults, foreign keys,
constraints and indexes. The findings below identify actual simplification
candidates; this documentation does not claim that every existing field is
essential or authorize deletion of stored history.

## Column and metadata review: 2026-09-21

A fresh PostgreSQL 14.23 database created from the current models contains 16
application tables and 9 Django tables, with 96 indexes. Read-only inspection
of the existing local database found identical table/column names, types and
nullability. Every physical column is covered in the dictionary. The additional
four-column `django_migrations` table is documented separately: it is absent
from this fresh draft schema and expected after release freeze.

### Decisions to make before freezing the release

| Field or group | What current code does | Review decision |
| --- | --- | --- |
| `account_profile.product_family` | Imported from legacy accounts and edited/displayed in [account admin](../frontend/accounts/admin/users.py); it does not participate in current product authorization. | Strongest candidate for retiring from the live schema. Decide whether the historical label needs an archive before removing the field, admin surface and importer mapping together. Product assignments already belong in `account_product_grant`. |
| `execution_job.result_metadata`, `result_sha256`, `result_received_at`, `qc_tool_version` | [Result processing](../frontend/dashboard/services/product_units/jobs/metadata.py) writes these snapshots. Searches of current application read paths found no consumer/verification of these stored job fields; report rendering still reads artifact files. | Decide whether PostgreSQL should supply report recovery and retained result evidence. Either implement that use and verification, or remove the unused copies in a reviewed schema change. A stored digest alone is not an integrity check. Keep `reference_period`: the [report serializer](../frontend/dashboard/services/jobs/serializers.py) already uses it as a fallback. |
| `storage_delivery_source.access_key`, `secret_key` | Plaintext operational credentials, actively used by [worker requests](../frontend/dashboard/views/workers.py), potentially repeated across many source records. | These are not unused fields, but credential storage deserves a release decision. Consider a credential reference/secret-store design separately; do not erase active credentials without replacing their retrieval path. The SQL-only legacy importer intentionally leaves them blank. |
| `account_product_grant.product_ident` | The [scope service](../frontend/accounts/services/products.py) accepts both business-product and executable-definition identifiers. The old model description implies only the latter. | Clarify the scope vocabulary/API contract before choosing a rename or catalog FK. Converting it directly to a product FK would discard definition-only scope and historical unresolved grants. |
| `submitted_product_unit_code` on delivery, job and receipt | Means ZIP-verified input identity, while `product_unit_code` is a job/display observation or expected catalog snapshot depending on the table. [Current job result application](../frontend/dashboard/services/product_units/results.py) writes the same value to both job unit fields; legacy imports may supply reported-only values. | Clarify the name and contract: "submitted" does not mean manager accepted. Assess duplication at the job level separately from the sticky delivery identity and immutable expected-versus-observed receipt evidence. Do not merge all similarly named columns. |
| `publication_submission.artifact_path` | Stores an absolute retained directory; [artifact validation](../frontend/dashboard/services/submissions/artifacts.py) checks it against the configured storage root. | A stable storage-relative key could simplify moving/restoring deployments. This is a compatibility improvement, not disposable metadata; existing immutable receipts must continue to resolve and verify. |

These are review candidates, not confirmed permission to delete data. In
particular, a field with no current UI reader can still be an intended audit
record. Decide that retention requirement explicitly before removing its writer.

### Lower-priority simplification and consistency

| Item | Assessment |
| --- | --- |
| `catalog_definition_revision.source_path` | Source provenance rather than the location used to retrieve original bytes. It is retained in [plan reconstruction](../frontend/dashboard/services/catalog/delivery_plans.py) and admin. Keep or remove based on an explicit provenance requirement; never replace original specification bytes by serializing JSONB. |
| `catalog_product_unit.created_at` | Usually duplicates the release's import timing. Low-impact removal candidate if there is no need for per-unit import timestamps. |
| `catalog_product_unit.source_value` and `provenance` | [Release validation](../frontend/dashboard/services/catalog/sync/release_validation.py) compares these values; original and normalized codes can differ. Keep their meaning. `provenance` is free text although current writers use a small vocabulary; consider a choices/CHECK contract. |
| `execution_job.job_status` and `request_source` | Current states/channels are validated by application paths, without SQL membership checks. Consider explicit enumerations/checks after accounting for supported legacy values. This is an integrity improvement, not metadata removal. |
| Version/revision nonnegative checks alongside stricter positive checks | Django positive-integer fields produce `>= 0` checks while some named business constraints require `> 0`. The weaker checks are redundant but cheap; removing business constraints would weaken validation. Avoid changing field ownership just to reduce this count. |
| `django_session` expired rows | Routine cleanup is supported by `clearsessions`; the table and active sessions remain required. This is a retention task, not a reason to remove session columns. |

### Deliberate duplication to retain

- Actor usernames and token IDs/names preserve who acted when accounts or
  credentials change. Token-ID snapshots are intentionally not foreign keys.
- API token permission/role/product/region snapshots prevent later account
  grants from silently expanding previously issued credentials.
- Product, release and specification descriptions can differ for grouped
  products. Delivery/job descriptions also keep legacy history readable when
  no authoritative catalog revision exists.
- Current review/conflict state supports lists and concurrency checks; event
  tables retain earlier decisions. These are separate current and historical
  facts, not two independent sources that can be updated arbitrarily.
- Readiness actor/time, scope digest and revision are required for explicit
  manager confirmation and invalidation when accepted coverage changes.
- `Delivery.date_submitted` retains legacy submission dates even when a verified
  modern publication receipt cannot be recovered. Dropping it would lose
  information from the available SQL-only backup.
- `account_profile.country` still identifies the delivery owner's region in
  [legacy region visibility](../frontend/dashboard/access/legacy_regions.py).
  Region grants describe the viewer's scope and cannot replace that fact.
  Changing the owner's country currently changes visibility of past deliveries;
  review that compatibility behavior before retiring the profile field.

### Enforcement and retention boundaries

The dictionary distinguishes SQL constraints from model/service rules. Many
cross-row checks, publication immutability and append-only event protections
live in Django code rather than PostgreSQL triggers. Publication checks cannot
prove that files still exist or that their hashes match. Nullable actor FKs
with stored usernames intentionally preserve attribution after detachment.

Django admin history is different: its actor relationship uses ORM `CASCADE`,
so hard-deleting an account can remove administration events. Prefer deactivation
when preserving historical users and deliveries; do not describe all audit
tables as deletion-proof. Framework metadata and its indexes remain owned by
Django's migrations.

No fields, tables or indexes were removed in this review. No migration baseline,
product specification or existing database was changed. Resolve agreed design
changes through the [draft/released lifecycle](MIGRATIONS.md), and update the
dictionary with them.

## Earlier table and index audit: 2026-09-18

Audited the local PostgreSQL schema read-only on 2026-09-18 and compared it with
Django model ownership, indexes and the publication workflow. The database
contained **25 tables: 16 application tables and 9 Django tables**. Table count
alone is not an optimization target. No existing database was reset or altered.

## Inventory and decisions

The [application schema](SCHEMA.md) lists every application table and its owning
model. These 16 tables have distinct responsibilities; column-level retention
decisions are reviewed above rather than inferred from table count:

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
