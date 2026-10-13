---
title: Testing
parent: Development
nav_order: 1
---

# Testing

Run focused tests first, then the relevant full suite. The GitHub Actions
frontend workflow is the authoritative frontend test contract.

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

The running worker provides its current Python and system dependencies:

```bash
docker compose -f docker/compose.local.yaml exec worker \
  python3 -m unittest \
    qc_tool.test.test_archive_security \
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

For production settings, run Django's deploy check with a long throwaway secret,
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
