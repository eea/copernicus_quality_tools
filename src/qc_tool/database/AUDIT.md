# Database audit and remaining release work

Updated **2026-09-21** for **QC Tool 3.0.0**. The schema is frozen in the separate
release candidate: [policy.json](policy.json) declares `released` and identifies
the two `0001_major_release` baselines. The verified released PostgreSQL schema
contains **24 tables, 193 columns, 120 constraints and 91 indexes**; see the
[complete dictionary](TABLES.md).

**Next step: record the release commit and CI results, then build and verify the
release images.** Publication is on hold until registry access is available.
The [3.0.0 release record](releases/3.0.0.md) separates verified source checks
from pending packaged-artifact checks, publication and production cutover.
No existing local or production database was upgraded by this freeze.

## Remaining release checklist

Keep items unchecked until their evidence is recorded for the selected release.
The [migration runbook](MIGRATIONS.md) owns the commands; this checklist tracks
what remains to be done.

### Before publication

- [ ] **Record the committed candidate and CI results.** Commit policy and both
  reviewed snapshots together in the separate freeze change. Record its immutable
  source SHA and passing CI for that exact revision in the
  [release record](releases/3.0.0.md). Local checks below passed against mounted
  candidate source; they do not prove the content of a published image.
- [ ] **Confirm registry access and publication configuration.** Publication
  remains on hold at the user's request until access is available. Record the
  intended registries and immutable frontend/worker image references before
  publishing or deploying anything.

- [ ] **Build and verify the release images.** Use a clean, committed source SHA
  for frontend and worker, or record and test compatibility of a retained worker.
  Run packaged-artifact checks **without checkout bind mounts**. Record immutable
  image digests and pin them in the target configuration; promote the same images.
  See [Prepare a release](MIGRATIONS.md#prepare-a-release).

### Before production cutover

- [ ] **Confirm the source snapshot and target.** Complete the release owner,
  target environment and manual cutover details in the release record. Confirm
  that the `20260907` SQL dump is the intended source and account for any later
  legacy writes. The available backup contains no ZIPs or QC result files.
- [ ] **Repeat the legacy import rehearsal with those images.** Follow
  [LEGACY_IMPORT.md](LEGACY_IMPORT.md) on a fresh isolated PostgreSQL target built
  from the frozen migrations. Compare the source checksum, dry-run/applied counts
  and converted fields. Record the omitted data and permission mappings. Historical
  submission dates remain history: missing files cannot create verified receipts
  or approval eligibility. The successful frozen-source rehearsal in the release
  record is the comparison point, not a substitute for the packaged-image run.
- [ ] **Prepare product access and replacement credentials.** Review the
  [access map or administrator assignments](LEGACY_IMPORT.md#2-review-user-access),
  including legacy staff accounts and unmapped permissions. After importing into
  each fresh target, manually upload the original specification JSONs and make
  any remaining administrator assignments to canonical product/definition scopes.
  Former country-based viewers need explicit product grants. Remove clients'
  dependence on the retired user-country API/export field and country/region CLI
  options; use the current documented routes.
  Replace old API credentials; replace S3 credentials for locations that will be
  used again. Update API clients to `verified_product_unit_code`. Existing
  versioned publication manifests retain their original keys and checksums.
- [ ] **Provision storage and verify recovery.** Record the new database and
  incoming/work/boundary/submission volumes. Configure persistent
  [S3 credential storage](../../../docs/deployment/operations.md#s3-credentials)
  with frontend ownership, directory mode `0700`, file mode `0600` and a restricted
  backup. Rehearse database/storage restore for the target configuration. Preserve
  the source dump and record the recovery procedure and rollback boundary.
- [ ] **Verify the complete user workflow.** With the candidate images, test
  login, allowed and denied product access, upload of a new representative delivery,
  worker QC, publication, individual/bulk review and explicit manager readiness.
  Test S3 registration/dispatch if enabled. Confirm that startup creates no products
  before an administrator uploads an original specification. Record results in
  the release record.
- [ ] **Complete and execute the cutover record.** Write the exact commands,
  stop conditions and recovery actions for the pinned target configuration.
  If the legacy deployment still runs, stop writes and drain/stop workers before
  the agreed source snapshot. Initialize the fresh release target with
  `database plan|apply|check`, then import and reconcile before starting target
  application writers. Switch traffic only
  after acceptance checks; record monitoring results and the recovery window.
  Follow the [manual cutover procedure](MIGRATIONS.md#one-time-manual-production-cutover).

## Frozen schema verification: 3.0.0

The separate release candidate contains initial snapshots for `accounts` and
`dashboard`, both named `0001_major_release`, with matching `released` policy.
The snapshots were reviewed for dependencies, model creation, indexes and
constraints; they contain no data import or product seeding. Original product
specifications and uploaded snapshots were not modified.

Verified on disposable targets using the mounted release-candidate source:

- SQLite and PostgreSQL baseline creation, synthetic-record preservation,
  repeat application, role bootstrap, declared constraints/indexes and model
  drift checks passed.
- All **1,091 application tests** passed on SQLite (eight skips) and PostgreSQL
  (two skips). Each backend now skips the draft-only history test; the other
  skips remain backend-specific or established test exclusions.
- All **109 JavaScript tests** and **33 host history/parser tests** passed.
- A fresh PostgreSQL legacy-import rehearsal preserved 97 users, 57,583 deliveries,
  61,319 jobs, 29,688 sources, 196 administration events and 15,992 historical
  submission dates. Converted user/source/delivery/job fields matched individually;
  no products or verified receipts were created, repeat import was refused and
  the source checksum was unchanged. See the [release record](releases/3.0.0.md).
- Read-only inspection of PostgreSQL **14.23** confirmed **24 tables, 193 columns,
  120 constraints and 91 indexes**. The dictionary matches all physical columns,
  null flags, constraints and indexes. The migration recorder is now part of the
  inventory; the three Django membership-table row IDs are `bigint` in the
  released schema.

These are source and disposable-database checks. Exact-commit CI, packaged-image
verification, registry publication, release-image import rehearsal and production
cutover remain separate checklist items above. Freeze does not adopt or fake the
new migration history onto an existing draft or legacy database.

## Column and metadata review: 2026-09-21

### Completed schema cleanup

These are implemented decisions, with no remaining implementation task in this
section. Existing databases, original specifications and uploaded snapshots were
not rewritten during cleanup. That draft had 23 tables and 189 columns; an earlier
iteration had 25 tables and 198 columns. The released inventory above adds Django's
migration recorder without restoring removed application metadata.

| Completed change | Retained behavior / reference |
| --- | --- |
| Removed the entire `account_profile` and `account_region_grant` tables. | Country-based authorization, region permissions, token region snapshots and user-country list/export fields are removed. Access uses product assignments and roles. The importer reports omitted source profiles and obsolete groups without recreating them. [Account access](../frontend/accounts/authorization/access.py), [importer](legacy/importer.py). |
| Removed job `result_metadata`, `result_sha256`, `result_received_at` and `qc_tool_version`. | Results and software version remain in artifact files; SQL retains the input hash and reference period used by publication/reporting. [Result projection](../frontend/dashboard/services/product_units/jobs/metadata.py). |
| Replaced S3 `access_key`/`secret_key` columns with `credential_ref`. | Private credential files are bound to the source location. Missing/unsafe credentials block QC; legacy imports restore no credentials. [Credential service](../frontend/dashboard/services/s3/credentials.py). |
| Clarified the textual product-grant scope. | Business-product and exact-definition grants retain distinct access behavior, including historical unresolved assignments. [Grant model](../frontend/accounts/models/product_grants.py), [scope service](../frontend/accounts/services/products.py). |
| Renamed ZIP identity to `verified_product_unit_code`. | Model, API, queries, exports and UI use the new name. Reported legacy units remain distinct; manifest v1/v2 bytes and keys remain compatible. [Unit contract](../../../docs/architecture/product-unit-metadata.md). |
| Replaced absolute publication `artifact_path` with relative `artifact_key`. | Storage-root relocation preserves receipts, downloads and retries. Unsafe keys are rejected. [Storage service](../frontend/dashboard/services/submissions/storage.py), [tests](../frontend/dashboard/services/tests/test_submission_storage.py). |
| Removed the `legacy` request channel. | QC jobs record browser/api or NULL when unknown; a SQL CHECK rejects unsupported values. Publication accepts browser/api only. |
| Removed superseded URL aliases, unused model helpers and the old unit-metadata backfill. | Current routes/services are the supported application interface. Geographic inputs in unchanged specifications and checksummed publication manifests retain their data contracts. |

### Retained for this release; optional future changes

These observations are explicitly deferred and do not block this release.
Any subsequent schema change needs a reviewed forward migration.

| Item | Decision for this release |
| --- | --- |
| `catalog_definition_revision.source_path` | Retain source provenance used by plan reconstruction/admin. Reconsider only with an explicit provenance requirement; original specification bytes remain immutable. |
| `catalog_product_unit.created_at` | Retain per-unit creation timing. Possible later removal has little impact and needs a clear retention decision. |
| Unit `source_value` and `provenance` | Retain both because release validation compares original and normalized values. A SQL restriction on provenance vocabulary is deferred. |
| Job `job_status` | Retain application state validation. Additional SQL membership checks can be considered independently of request-channel validation. |
| Nonnegative checks alongside stricter positive checks | Retain both; the stronger business constraints remain necessary. |

Schedule [`clearsessions`](../../../docs/deployment/operations.md#session-maintenance)
as routine operations. Expired session cleanup does not require a schema change.

### Deliberate duplication to retain

- Actor usernames and token IDs/names preserve who acted when accounts or
  credentials change. Token-ID snapshots are intentionally not foreign keys.
- API token permission/role/product snapshots prevent later account
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

### Earlier draft verification: 2026-09-21

Before freeze, fresh SQLite and PostgreSQL schema probes passed for the 23-table draft,
including repeat initialization, account roles, constraints and index checks.
The dictionary at that stage was verified from a fresh PostgreSQL 14.23 database:
189 columns, 119 constraints and 90 indexes.

- The 1,091-test application suite passed on SQLite (seven skips) and PostgreSQL
  (one skip). The 109 JavaScript tests and 33 host history/parser tests passed
  separately. WSGI imports, Django checks and the draft history gate passed.
- The unchanged 20260907 SQL dump was imported into a separate fresh PostgreSQL
  target. All 97 users, 29,688 storage sources, 57,583 deliveries and 61,319 jobs
  matched the prepared conversion field by field. It retained 196 administration
  events and 15,992 historical submission dates.
- The import omitted 52 profiles, six obsolete groups and 12 memberships. Only
  current roles were created. Unknown job request origin is NULL; no profile or
  region tables, region permissions, products or verified receipts were created.
  Reimport into the occupied target was refused and the source checksum matched.
- During schema cleanup, original specifications, uploaded specification snapshots,
  existing databases and migration policy were unchanged. Regression verification
  used disposable targets.

### Local review database reset: 2026-09-21

At the user's explicit request, the local development `qc_tool` database was
backed up in the ignored `backups/` directory, recreated, and initialized through
the whole-app database command. That reset produced 23 tables, 189 columns and
90 indexes, with no retired profile/region tables or country columns. Products,
deliveries, jobs and product assignments start empty. Startup creates the three
standard local demo accounts. This describes the earlier local review state,
not the isolated 24-table release verification database.

Database readiness and Django checks passed. Authenticated dashboard, product,
delivery and reviewer pages returned HTTP 200 for the applicable demo roles;
the product list is empty for all three. Shared files and original specifications
were preserved. The policy was still `draft` at the time of that reset. The
separate 3.0.0 freeze changes the release policy; it does not upgrade or reset
that existing local database. The earlier reset was not a production-cutover
rehearsal.

## Earlier index audit: 2026-09-18

The earlier audit consolidated terminology around `product_unit` and removed
11 redundant foreign-key indexes covered by composite indexes. The accepted
candidate uniqueness constraint and readiness actor reference added two indexes,
bringing the total from 105 to 96 across the same 25 tables. These changes are
already implemented; the original local database was not altered.

Retain composite uniqueness, reverse unit lookup, queue indexes and publication
receipts. Further index tuning should follow production query plans and observed
load. No latency improvement is claimed from the small local dataset.

The [application schema](SCHEMA.md) owns the table inventory and persistence
contracts. The historical results remain background evidence; the current frozen
schema checks and pending release operations are recorded above and in the
[3.0.0 release record](releases/3.0.0.md).
