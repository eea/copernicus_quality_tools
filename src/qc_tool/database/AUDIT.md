# Database audit and remaining release work

Updated **2026-10-13** for QC Tool **v3.0.0 models-only initialization and manual
legacy handoff**. Current models own the whole schema. There are no first-party
migration packages, retained legacy converters, baseline snapshots, source
history correction machinery or future released-migration execution paths.

The Delivery model retains its nonunique conditional `LOWER(filename)` index
for submitted-history lookup. Historical submission dates preserve duplicate
admission protection without manufacturing modern receipts or approvals.
Original product specifications and protected raster/vector checks are unchanged.

## Remaining release checklist

Use [initialization](MIGRATIONS.md), [manual restore](MANUAL_RESTORE.md) and the
[release record](releases/3.0.0.md) from the selected source. Complete a gate only
when its actual evidence is available.

### Before publication

- [x] Verify fresh model-created schemas on SQLite and PostgreSQL, guarded empty
  initialization, read-only existing-schema checks/application and schema refusal.
- [ ] Run the frontend, authorization, history duplicate-blocking and offline
  maintainer-tool tests for this source.
- [ ] Build and verify the selected frontend and worker artifacts without source
  overlays, and record immutable image digests. A runtime image with a checkout
  overlay establishes source testing only.
- [ ] Record registry publication, release tagging and production installation
  separately; local database preparation performs none of these operations.

### Before manual production installation

- [x] Restore the prepared native PostgreSQL archive into a new empty isolated
  target; compare the checksum, schema, counts, retained fields and sequences.
- [ ] Record source completeness accurately. Available historical SQL and web
  exports have different capture dates and are not a coherent current snapshot.
- [ ] Provision authorized account passwords and canonical product grants.
  The available user export does not provide complete password hashes.
- [ ] Upload unchanged original specifications and restore/provision shared
  delivery, report, publication, boundary and private credential storage.
- [ ] Verify the exact image pair: login, denied/allowed access, upload, worker QC,
  submission, review and manager readiness. Same-input production/v3 acceptance
  must agree except for damaged ZIPs; this database task does not prove parity.
- [ ] Coordinate source writes, backup/recovery copies and target traffic. Restore
  and configure a fresh target before manually switching production.

The initializer supports an explicit completely new production installation.
Startup checks readiness and never automatically creates a production schema.
Existing matching schemas are read-only no-ops; partial, legacy and outdated
schemas are refused. The operator must never use an empty catalog as evidence
that an occupied database is disposable.

Legacy conversion source and personal-data artifacts are preserved privately,
excluded from Git and not shipped as maintained commands. A future migration
workflow, starting no earlier than 3.0.1, needs its own reviewed transition;
it is not prebuilt or activated by this version.

## Column and metadata review: 2026-09-21

### Completed schema cleanup

These are implemented decisions, with no remaining implementation task in this
section. Existing databases, original specifications and uploaded snapshots were
not rewritten during cleanup. These model decisions are retained in the current
models-only schema; the physical inventory must be checked on a fresh target.

| Completed change | Retained behavior / reference |
| --- | --- |
| Removed the entire `account_profile` and `account_region_grant` tables. | Country-based authorization, region permissions, token region snapshots and user-country list/export fields are removed. Access uses product assignments and roles. Manual conversion omits obsolete profile/region authorization; it does not recreate those tables. [Account access](../frontend/accounts/authorization/access.py). |
| Removed job `result_metadata`, `result_sha256`, `result_received_at` and `qc_tool_version`. | Results and software version remain in artifact files; SQL retains the input hash and reference period used by publication/reporting. [Result projection](../frontend/dashboard/services/product_units/jobs/metadata.py). |
| Replaced S3 `access_key`/`secret_key` columns with `credential_ref`. | Private credential files are bound to the source location. Missing/unsafe credentials block QC; the prepared historical copy contains no credentials. [Credential service](../frontend/dashboard/services/s3/credentials.py). |
| Clarified the textual product-grant scope. | Business-product and exact-definition grants retain distinct access behavior, including historical unresolved assignments. [Grant model](../frontend/accounts/models/product_grants.py), [scope service](../frontend/accounts/services/products.py). |
| Renamed ZIP identity to `verified_product_unit_code`. | Model, API, queries, exports and UI use the new name. Reported legacy units remain distinct; manifest v1/v2 bytes and keys remain compatible. [Unit contract](../../../docs/architecture/product-unit-metadata.md). |
| Replaced absolute publication `artifact_path` with relative `artifact_key`. | Storage-root relocation preserves receipts, downloads and retries. Unsafe keys are rejected. [Storage service](../frontend/dashboard/services/submissions/storage.py), [tests](../frontend/dashboard/services/tests/test_submission_storage.py). |
| Removed the `legacy` request channel. | QC jobs record browser/api or NULL when unknown; a SQL CHECK rejects unsupported values. Publication accepts browser/api only. |
| Removed superseded URL aliases, unused model helpers and the old unit-metadata backfill. | Current routes/services are the supported application interface. Geographic inputs in unchanged specifications and checksummed publication manifests retain their data contracts. |

### Retained for this release; optional future changes

These observations are explicitly deferred and do not block this release.
In 3.0.0, schema changes remain models-only and require fresh disposable
verification. Migration management can be introduced separately in 3.0.1 or later; no
upgrade machinery is included in this release.

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
Django under the selected schema policy. v3.0.0 has no migration recorder or applied history.
