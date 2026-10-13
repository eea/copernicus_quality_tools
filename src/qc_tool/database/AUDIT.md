# Database audit and remaining release work

Updated **2026-10-13** for the corrected **QC Tool 3.0.0 models-only policy**.
[policy.json](policy.json) is `draft` with no baseline identities. Version 3.0.0
contains no first-party migration definitions or schema snapshots. The first
migration-managed freeze is reserved for **3.0.1 or a later reviewed release**.

The case-insensitive legacy submission lookup retains its nonunique partial
`LOWER(filename)` index in the Delivery model. A fresh models-only target creates
it directly; it is not a forward migration or a global filename constraint.
No existing database is reset, adopted, or upgraded by this source correction.
See the [table dictionary](TABLES.md) and [release record](releases/3.0.0.md).

Fresh models-only PostgreSQL verification on 2026-10-13 measured **23 tables,
189 columns, 119 constraints and 91 indexes**. The migration recorder is absent
and no migrations are applied. Schema/roles/repeated initialization checks and
**103 focused regression tests** passed on that isolated target. This is source
verification; packaged artifact and production acceptance checks remain pending.
The fresh SQLite target also passed schema checks and the same focused suite:
103 tests collected, 100 passed and 3 PostgreSQL-only skips. It has 23 tables and
189 columns without a migration recorder or applied history. These results are
not a full frontend, worker parity or packaged-artifact certificate.

Earlier frozen-candidate checks and packaged artifacts describe a superseded
schema experiment. They do not certify the corrected source, its models-only
initialization, or a deployable frontend/worker pair. Rebuild and verify artifacts
from the selected source before publication. Current secure-environment database
commands remain blocked; production initialization is a separate unresolved gate.

## Remaining release checklist

The [runbook](MIGRATIONS.md) owns commands. Record evidence for the exact selected
source and keep incomplete items unchecked.

### Before publication

- [x] **Verify the corrected source policy and schema.** Confirm no first-party
  migration definitions or snapshots; test model initialization, repeated
  initialization, retained synthetic data, roles and declared indexes/constraints
  on fresh SQLite and PostgreSQL targets. Record the actual physical inventory.
- [ ] **Run application and tooling checks for that source.** Include legacy
  import reconciliation and duplicate filename admission/submission behavior.
  Prior tests against the removed migration graph are historical evidence only.
- [ ] **Build and verify both release artifacts.** Pin the committed source SHA,
  validate the packaged models-only policy without checkout mounts, and record
  immutable frontend/worker image digests. Do not reuse the earlier frozen image.
- [ ] **Confirm publication access and source mapping.** Registry publication,
  release tags and production deployment remain separate operator actions.

### Before production cutover

- [ ] **Resolve the production initialization gate.** The current command refuses
  `draft` policy in a secure environment. Do not bypass it with fake records,
  a database reset, or a 3.0.0 migration baseline. Record the explicitly reviewed
  production procedure before attempting a cutover.
- [ ] **Confirm source completeness and fresh targets.** Obtain a coherent
  database/storage snapshot or label the available mixed history accurately.
  Preserve originals; use new database and storage locations. No empty-catalog
  assumption permits resetting an occupied database.
- [ ] **Rehearse the supported record conversion.** Use
  [LEGACY_IMPORT.md](LEGACY_IMPORT.md) and the
  [local wrapper](LOCAL_LEGACY_REHEARSAL.md) on isolated fresh targets. Reconcile
  ownership, permission mappings, timestamps and omitted evidence. Historical
  submission dates do not create verified publication receipts or approvals.
- [ ] **Review access and replacement credentials.** Assign canonical product
  scopes explicitly, issue new API/S3 credentials where needed, and upload the
  unchanged original specifications through the supported administration flow.
- [ ] **Restore files and prove recovery.** Reconcile incoming/work/submission
  storage and boundary references with the database; test target backup/restore.
  SQL alone cannot reconstruct ZIPs, detailed QC reports or published folders.
- [ ] **Verify the full workflow and strict QC acceptance parity.** Test allowed
  and denied access, new delivery upload, duplicate history rejection, worker QC,
  publication, review and manager readiness with the actual image pair. The
  historical sample comparisons are not a current-production parity certificate.
- [ ] **Record the cutover and recovery window.** Coordinate source writes and
  workers, use the final agreed snapshot, validate before changing traffic, and
  keep a recovery copy without accepting writes in both systems.

## First migration-managed release: 3.0.1 or later

Review its initial schema definitions and policy transition together. Existing
3.0.0 schemas have model-created tables but no first-party migration history.
Initial migrations cannot simply be run over those tables. Prepare a separate
fresh-target data conversion or an explicitly approved adoption design with
schema, data and storage reconciliation. This project does not promise an
automatic adoption path, `--fake-initial`, recorder rewriting or database reset.
After that reviewed freeze, preserve established identities and add forward
migrations normally.

## Column and metadata review: 2026-09-21

### Completed schema cleanup

These are implemented decisions, with no remaining implementation task in this
section. Existing databases, original specifications and uploaded snapshots were
not rewritten during cleanup. These model decisions are retained in the current
models-only schema; the physical inventory must be checked on a fresh target.

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
In 3.0.0, schema changes remain models-only and require fresh disposable
verification. After the first reviewed freeze in 3.0.1 or later, schema changes
require forward migrations.

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
Django under the selected schema policy. Migration history is enabled only after
the future reviewed freeze.

## Historical verification background

Earlier draft-model review verified 23 tables and 189 columns on a separate
PostgreSQL target before the submitted-filename index was added. The historical
application suite and legacy conversion checks remain evidence for that earlier
source, not for the corrected current candidate.

The subsequent unpublished frozen-candidate attempt is preserved in Git history
([freeze source](https://github.com/eea/copernicus_quality_tools/commit/e7a699d9e182ceda7f2906549461c83807bf1b74),
[evidence source](https://github.com/eea/copernicus_quality_tools/commit/c5837c6eda58df6fab5727a6e6d730ffc416a89b)).
Its migration definitions and policy are superseded for 3.0.0. Existing rehearsal
or development databases from any earlier attempt are not automatically changed
by the corrected source policy and must not be repurposed as release targets.

The [application schema](SCHEMA.md) owns model responsibilities; the
[release record](releases/3.0.0.md) records current decisions and pending evidence.
