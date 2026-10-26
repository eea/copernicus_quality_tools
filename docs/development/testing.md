---
title: Testing
parent: Development
nav_order: 1
---

# Testing

Administrative record-transfer tests are discovered by the existing
`qc_tool.database.tests.integration` and dashboard test suites. The transfer
service tests use real transaction boundaries on disposable databases and inject
precommit failure, lost COMMIT acknowledgement, interrupted status persistence
and terminal-journal cleanup failures. Application tests include real publication
manifests, original specification bytes, account mapping and file rollback.
Run both SQLite and PostgreSQL; configure PostgreSQL with `DB_ENGINE=postgres`.
Tests never restore into or reset a retained deployment database.

Run focused tests first, then the relevant full suite. The GitHub Actions
integration workflow is the authoritative frontend test contract. See
[continuous integration](continuous-integration.md) for job ownership, browser
smoke coverage, reusable commands and the required **CI** result.

## Native PostgreSQL backup and restore

Both frontend images package the reviewed PostgreSQL 14 client tools. CI checks
`pg_dump --version` and `pg_restore --version` inside the packaged frontend;
installing `psycopg2-binary` does not satisfy this requirement. The signed PGDG
repository/key and exact client package are pinned in each frontend Dockerfile.
The selected package is available for both AMD64 and ARM64. A native operation
requires its client major to match the source/target PostgreSQL server major.

Run native integration checks only against disposable PostgreSQL databases.
Fixtures must exercise a full archive and separately provisioned empty target,
including stored password hashes, API credential digests, sessions, receipt rows,
unmanaged tables/columns, sequences and schema objects. Compare the complete
source and restored data rather than only model-managed fields. The portable
account/application privacy and graph tests continue to enforce their filtered
contract independently.

Native refusal/recovery coverage includes fresh-target creation permissions,
the serving database, occupied or foreign schemas, tool/server major mismatch, malformed or
changed archives, failed restoration and uncertain COMMIT acknowledgement.
Assertions establish that restoration preserves the serving database and active
selection. Explicit activation tests cover preflight, administrator credential
proof, retained source access, revision checks, request/stream pinning and
same-maintenance-generation rollback. Test-runner `NAME` overrides must never
follow the deployment pointer. Never use an existing developer/production database as a test
restore destination, create/drop it from application tests, or initialize a full
archive destination with `database apply` first. Keep real credential-bearing
backups out of test logs and CI artifacts.

## Maintainer-tool tests on the host

Run from the repository root with Python 3.11 or newer:

```bash
python3 -m unittest discover -s scripts/tests -t . -v
```

These repeatable tests cover the QC evidence runner. They use temporary files
and synthetic records; they do not connect to production, initialize an
application database, start Docker, or execute real QC jobs. The frontend workflow runs this suite
in a separate **Maintainer tools (offline)** job.

Keep tests for tools under `scripts/tests/`, grouped by the tool's purpose.
Core QC and archive-security regression tests remain under `src/qc_tool/test/`;
frontend and database tests stay with their owning application packages. See
[Script organization and lifecycle](scripts.md) for retained tools, one-time
operations, historical experiments and proposed removals.

## Frontend checks in the local stack

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage check

docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database check

docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage collectstatic --noinput
```

The checkout is mounted read-only. Current Django models define the schema;
no migration files, converter or automatic schema-upgrade path are maintained.
Use a new disposable database after model changes. `database check` validates
an existing schema without modifying it.

## Models-only schema checks

CI verifies the models-only source contract and runs the frontend suite on
SQLite and PostgreSQL. It rejects first-party migration packages and application
conversion machinery and builds the schema directly from current models. Integration tests
exercise schema validation, initialization, permissions, synthetic records,
repeat initialization and refusal of unsafe existing schemas. They do not
convert or upgrade old production data.

The inspector validates the required model contract, including named `Meta`
CHECK predicates, SQLite JSON validity and declared index definitions. It does
not exhaustively compare field-generated positive-integer checks, arbitrary
extra SQL constraints, triggers or privileges. Fresh Django initialization
still creates its generated rules; physical inventory and data/access/storage
validation remain separate evidence for a prepared restore.

Follow the [database runbook](../../src/qc_tool/database/MIGRATIONS.md) for complete
local verification. For a disposable SQLite schema check in a one-shot container:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps \
  -e QC_TOOL_ENVIRONMENT=test \
  -e DB_ENGINE=sqlite \
  -e FRONTEND_DB_PATH=/tmp/qc-tool-schema-check.sqlite3 \
  -e WORK_DIR=/tmp/qc-tool-schema-check-work \
  frontend python3 -m qc_tool.database.checks.schema
```

This overrides ordinary frontend startup and uses container-local temporary
storage removed with the container. It requires a test environment and an empty
disposable database. Use a dedicated empty PostgreSQL test target for the other
backend. Add focused tests when changing model constraints, indexes or schema
validation; preserve application records during repeated checks.

## Frontend regression suite

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage test \
    qc_tool.database.tests.integration \
    qc_tool.frontend.accounts.tests \
    qc_tool.frontend.dashboard.services.tests \
    qc_tool.frontend.dashboard.tests
```

These explicit package labels include the central database integration tests
and both dashboard test packages while avoiding the historical
`dashboard/tests.py` discovery-name collision. Run the models-only source
contract tests and source gate separately on the host:

```bash
PYTHONPATH=src python3 -m unittest qc_tool.database.tests.test_source
PYTHONPATH=src python3 -m qc_tool.database.checks.source
```

The source gate reads the current source layout and policy. It has no comparison
commit or migration-history reset mechanism.

Upload feedback also has JavaScript event tests. Run them with Node.js 22:

```bash
node --test src/qc_tool/frontend/dashboard/tests/javascript/*.test.cjs
```

CI runs these explicitly on the host. The Python adapter runs them when Node.js
is installed and skips them inside the Python-only frontend image. They cover
shared selection and feedback behavior, failed and partial uploads, successful
registration feedback, cancellation and authentication redirects. See
[Upload pages](upload-pages.md) for the shared component contract and browser
checks for delivery, boundary and product adapters.

High-risk changes should include focused coverage for:

- anonymous, authenticated, and forbidden route behavior;
- role and direct-permission combinations;
- ownership and product scope;
- CSRF enforcement for session mutations;
- malformed identifiers and content types;
- path traversal, symlinks, archive limits, and cleanup;
- transaction rollback and partial failure;
- cache and credential response headers.

## Worker infrastructure/security tests

Build the current worker runtime before relying on its Python and system
dependencies. Current source over an older Python 3.8 image is unsupported:

```bash
docker compose -f docker/compose.local.yaml build worker
```

The worker image build and entrypoint verify Python 3.11 or newer, GDAL 3.8.4,
the required raster/vector/Parquet drivers and application adapter imports.
CI builds this image from the proposed checkout, runs `pip check`, starts only a
disposable embedded scratch PostgreSQL and executes the full synthetic worker
suite with external INSPIRE calls disabled. It does not validate live INSPIRE,
S3 service availability or customer-file QC parity.

```bash
docker compose -f docker/compose.local.yaml exec worker \
  python3 -m unittest \
    qc_tool.test.test_archive_security \
    qc_tool.test.test_worker_archives \
    qc_tool.test.test_worker_module_boundaries \
    qc_tool.test.test_product_security \
    qc_tool.test.test_worker_auth \
    qc_tool.test.test_worker_job_contracts \
    qc_tool.test.test_worker_job_identifiers \
    qc_tool.test.test_worker_s3_delivery \
    qc_tool.test.test_worker_scheduler \
    qc_tool.test.test_worker_service_auth
```

These tests exercise worker contracts and security adapters without changing
specific raster/vector QC behavior.

Maintenance admission/process-group tests also run as a small host job in CI:

```bash
PYTHONPATH=src python3 -m unittest \
  qc_tool.test.test_maintenance_protocol \
  qc_tool.test.test_worker_auth \
  qc_tool.test.test_worker_maintenance \
  qc_tool.test.test_worker_scheduler \
  qc_tool.test.test_worker_service_auth
```

They need Bottle and a POSIX process environment. They use synthetic subprocesses,
including a child process, and do not connect to application/worker databases.
Frontend maintenance regressions are discovered by the existing frontend suite:
`dashboard.tests.test_admin_maintenance`, `dashboard.tests.test_maintenance` and
`dashboard.services.tests.test_maintenance` under the full package prefix above.
They exercise read-only sessions, cross-process admission/stream draining,
worker acknowledgments, role/CSRF controls and terminal job history. Maintenance
coverage also checks bounded parallel probes, strict shared wire contracts,
service-owned worker retirement, prefixed routes, readiness observation times
and nonzero operator-command results while stopping remains incomplete. Worker
coverage must include repeated authority polling under continuous short-job
load and a dead scheduler causing closed admission plus unhealthy liveness.

### Read-only maintenance matrix

Run these checks in both stopping and ready phases, with ordinary users, scoped
product managers, administrators/superusers, existing API credentials and
anonymous/expired/invalid sessions. Use synthetic fixtures and disposable
SQLite/PostgreSQL targets. Capture SQL to reject DML as well as comparing retained
rows, because an unchanged final snapshot alone can miss attempted writes.

| Boundary | Expected evidence |
| --- | --- |
| Browser/API reads | Authorized pages, lists, history/results, Admin records and retained downloads remain available; forbidden/out-of-scope/missing objects preserve their usual denials; no session, last-login, token-use, Job or Delivery writes |
| Safe POST reads | `table_export`, `delivery_upload_check` and persisted-status `update_job` work with their normal CSRF, account and payload limits; no worker refresh or DB/filesystem mutation |
| Mutating requests | Upload registration/chunks/finalization and GET probes, QC claims/creation, publication/reviews, ordinary Admin POSTs, profile/password/token changes and login/logout return maintenance denial before DB or shared-file changes |
| Hidden writes | Invalid-session cleanup, async session methods, `SESSION_SAVE_EVERY_REQUEST`, API token throttling, status/history refresh and lazy Admin content-type creation cannot persist writes; unexpected ORM writes are blocked |
| Admission and streaming | Pre-enable admitted requests drain before ready; newly admitted maintenance reads/streams do not hold the writer barrier or invalidate readiness; worker acknowledgments remain required |
| Presentation | Persistent maintenance notice, disabled mutating controls and visible read controls agree across normal pages, Admin and login; direct calls remain blocked after bypassing disabled UI controls |
| Route/storage failure | Named routes work under URL prefixes; unclassified effects and missing/corrupt/unsafe maintenance state fail closed; authorization remains enforced |

The original maintenance tests are in `dashboard.tests.test_maintenance`,
`test_admin_maintenance`, `test_maintenance_streaming` and
`test_maintenance_control_routes`; read-only browsing coverage is in
`test_maintenance_browsing`, `test_maintenance_reads` and `test_maintenance_ui`.
Session, route-policy, table-export and
history/status regression packages provide the corresponding normal-mode
contracts. Update their previous blanket-503 assumptions when extending browsing;
retain writer-fence, generation, worker and storage safety assertions.

## Full QC test suite

The complete suite exercises actual raster/vector checks and needs the worker's
PostGIS/GDAL environment and test data:

```bash
docker compose -f docker/compose.local.yaml exec \
  -e SKIP_INSPIRE_CHECK=yes \
  worker python3 -m unittest discover qc_tool.test
```

Expect this suite to be substantially slower. Run relevant product/check tests
when validating recipes or QC behavior. Keep product specifications and uploaded
snapshots unchanged; raster/vector checks remain unchanged on this branch.

For genuine archived production inputs, follow [Legacy QC parity](legacy-qc-parity.md).
It documents isolated execution, identical-input evidence, accepted and rejected
controls, specification scope and coverage gaps.

## Static and configuration checks

```bash
# Compose files
docker compose -f docker/compose.local.yaml config --quiet

# JavaScript syntax (requires Node.js on the host)
rg --files src/qc_tool/frontend/dashboard/static -g '*.js' \
  | xargs -n 1 node --check

# Patch hygiene
git diff --check
```

Frontend CI builds from the repository root and tests the source packaged in the
image without a checkout bind mount. Local database archives and operator work
are excluded by `.dockerignore`. For production settings, run Django's deploy
check with `--deploy --fail-level WARNING`, a long throwaway secret,
an explicit test hostname, and HTTPS/HSTS settings matching the deployment.
Never weaken the check or commit its secret.

## Central database source contract

v3.0.0 has no migration framework, first-party definitions, initial snapshots or
legacy converter. Fresh schemas are built from current models. Initial migration
definitions may be introduced only in a separately reviewed 3.0.1-or-later release
with an explicit transition contract; this branch provides no future migration
machinery.

The [whole-application database runbook](../../src/qc_tool/database/MIGRATIONS.md)
and [`policy.json`](../../src/qc_tool/database/policy.json) govern every component.
Production may initialize an entirely empty database using the same explicit
command. `plan` and `check` inspect schema read-only; `apply` refuses partial or foreign schemas and
detected model drift and leaves a complete current schema unchanged.

The workflow uses SQLite and PostgreSQL 14. PostgreSQL tests additionally
exercise serialization between concurrent initialization jobs and restoration
of timeout settings. Do not use `--keepdb` across model schema changes.

A disposable schema fixture is not a production restore, release-to-release or
load test. Prepared data copies require private reconciliation, corresponding
storage and a restore rehearsal. Record matching source/image identifiers and
evidence limits in the [release record](../../src/qc_tool/database/releases/3.0.0.md).
CI success alone cannot promise zero downtime.
