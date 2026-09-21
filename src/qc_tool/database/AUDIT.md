# Database audit and remaining release work

Updated **2026-09-21**. Schema cleanup and removal of obsolete profile/region access are implemented
in the working tree. The current draft contains **23 tables, 189 columns and 90
indexes**; see the [complete dictionary](TABLES.md).

**Next step: review and commit the cleanup, then freeze the schema in a separate
release-preparation change.** [policy.json](policy.json) still declares `draft`
with no baselines. The earlier test and import results below verify the draft
models; they do not establish a frozen release or a completed production cutover.

## Remaining release checklist

Keep items unchecked until their evidence is recorded for the selected release.
The [migration runbook](MIGRATIONS.md) owns the commands; this checklist tracks
what remains to be done.

### Before freezing

- [ ] **Review and commit the final draft schema.** Review [TABLES.md](TABLES.md)
  against the intended release, including the retained/deferred decisions below.
  Include the application code and tests that use the renamed fields. The completed
  changes below include removal of obsolete profile/region access.
- [ ] **Start the release record.** Copy [RELEASE_TEMPLATE.md](RELEASE_TEMPLATE.md)
  into the release PR or deployment records. Choose the release version, owner,
  target environment and manual legacy-cutover path. Confirm that the
  `20260907` SQL dump is the intended source snapshot and account for any later
  legacy writes; the available backup contains no ZIPs or QC result files.

### Freeze the schema

- [ ] **Create the separate freeze change.** Follow
  [Freeze the first release](MIGRATIONS.md#freeze-the-first-release): generate
  `accounts/0001_major_release.py` and `dashboard/0001_major_release.py` under
  the central migration package together with policy `released` and the
  matching baseline identities. Review the operations and
  dependencies. Do not fake these migrations onto an existing draft database.
- [ ] **Verify the released migration graph.** Run history, model-drift, schema
  and application checks on fresh SQLite and PostgreSQL targets. Verify role
  bootstrap, repeat application, and an empty product catalog. Refresh the
  dictionary from that released schema, including `django_migrations` (currently
  documented separately). After these checks pass, commit policy and snapshots
  together in the freeze change. Record CI results for that exact candidate.

### After freezing, before production cutover

- [ ] **Build and verify the release images.** Use a clean, committed source SHA
  for frontend and worker, or record and test compatibility of a retained worker.
  Run packaged-artifact checks **without checkout bind mounts**. Record immutable
  image digests and pin them in the target configuration; promote the same images.
  See [Prepare a release](MIGRATIONS.md#prepare-a-release).
- [ ] **Repeat the legacy import rehearsal with those images.** Follow
  [LEGACY_IMPORT.md](LEGACY_IMPORT.md) on a fresh isolated PostgreSQL target built
  from the frozen migrations. Compare the source checksum, dry-run/applied counts
  and converted fields. Record the omitted data and permission mappings. Historical
  submission dates remain history: missing files cannot create verified receipts
  or approval eligibility. The successful draft rehearsal below is the comparison
  point, not a substitute for this run.
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

## Column and metadata review: 2026-09-21

### Completed schema cleanup

These are implemented decisions, with no remaining implementation task in this
section. Existing databases, original specifications and uploaded snapshots were
not rewritten. The draft now has 23 tables and 189 columns; the earlier cleanup had 25 tables
and 198 columns.

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
After freeze, any schema change needs a reviewed forward migration.

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

### Current draft verification

Fresh SQLite and PostgreSQL schema probes pass for the current 23-table schema,
including repeat initialization, account roles, constraints and index checks.
The table dictionary is regenerated from a fresh PostgreSQL 14.23 database:
189 columns, 119 constraints and 90 indexes.

- The 1,091-test application suite passed on SQLite (seven skips) and PostgreSQL
  (one skip). The 109 JavaScript tests and 33 host history/parser tests passed
  separately. The current WSGI imports, Django checks and draft history gate pass.
- The unchanged 20260907 SQL dump was imported into a separate fresh PostgreSQL
  target. All 97 users, 29,688 storage sources, 57,583 deliveries and 61,319 jobs
  matched the prepared conversion field by field. It retained 196 administration
  events and 15,992 historical submission dates.
- The import omitted 52 profiles, six obsolete groups and 12 memberships. Only
  current roles were created. Unknown job request origin is NULL; no profile or
  region tables, region permissions, products or verified receipts were created.
  Reimport into the occupied target was refused and the source checksum matched.
- Original specifications, uploaded specification snapshots, existing databases
  and migration policy were unchanged. Verification used disposable targets.

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
contracts. The earlier test totals are superseded by the current draft verification
above; record the eventual frozen-release results in the release record.
