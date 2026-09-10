---
title: Testing
parent: Development
nav_order: 1
---

# Testing

Run focused tests first, then the relevant full suite. The GitHub Actions
frontend workflow is the authoritative frontend test contract.

## Frontend checks in the local stack

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage check

docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage makemigrations --check --dry-run

docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage collectstatic --noinput
```

The checkout is mounted read-only. In draft, tests create tables directly from
models; no migration files are maintained and the drift command has no history
to compare. After release freeze, drift checks compare models with committed
migrations. Use the writable environment in
[Database migrations](../../src/qc_tool/database/MIGRATIONS.md#development-after-the-major-release-is-frozen)
to author reviewed new migrations.

## Migration checks

CI enforces the phase declared in `src/qc_tool/database/policy.json` and runs
the frontend suite on SQLite and PostgreSQL. In draft, it rejects migration
files and creates the schema directly from current models. After freeze, it
checks immutable history, baseline-to-head upgrades and model drift. Both modes
exercise synthetic records, permissions and repeat initialization/application.
Neither imports or upgrades old production data.

The complete [local verification procedure](../../src/qc_tool/database/MIGRATIONS.md#local-verification)
is maintained in the database runbook. For a quick schema check, use a disposable
SQLite database in a one-shot container:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps \
  -e QC_TOOL_ENVIRONMENT=test \
  -e DB_ENGINE=sqlite \
  -e FRONTEND_DB_PATH=/tmp/qc-tool-migration-check.sqlite3 \
  -e WORK_DIR=/tmp/qc-tool-migration-check-work \
  frontend python3 -m qc_tool.database.checks.schema
```

The command overrides ordinary frontend startup and uses container-local
temporary storage removed with the container. It does not require the local
database service to be running. The check requires a test environment and
refuses a populated database. Follow the runbook for its PostgreSQL equivalent
with a dedicated empty test database. Add
focused predecessor-to-successor migration tests for data transformations or
constraints that need additional historical fixtures.

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
`dashboard/tests.py` discovery-name collision. The migration-history unit tests
run separately on the host because they use Git, which is not part of the
frontend runtime image:

```bash
PYTHONPATH=src python3 -m unittest qc_tool.database.tests.test_history
PYTHONPATH=src python3 -m qc_tool.database.checks.history --base <commit>
```

Use the PR base or push predecessor as `<commit>` for the history comparison.

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
- ownership and product/region scope;
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

Expect this suite to be substantially slower. Run the relevant product/check
tests whenever changing `product_definitions/`, `raster/`, or `vector/`.

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

## Central database release policy

The [whole-application migration runbook](../../src/qc_tool/database/MIGRATIONS.md) and
[`src/qc_tool/database/policy.json`](../../src/qc_tool/database/policy.json) govern every component.
When the policy phase is `draft`, CI rejects every first-party migration
definition and tests schemas built directly from models. Release freeze
introduces the first snapshots; the `released` phase enforces immutable history
and reviewed forward migrations.

The workflow uses SQLite and PostgreSQL 14. PostgreSQL tests additionally
exercise serialization between concurrent migration jobs and timeout
restoration. Do not use `--keepdb` across draft schema changes.

The generic baseline fixture is not a release-to-release or load test. A future
data migration also needs a predecessor fixture and expected transformation;
an online release needs old/new application compatibility and representative
PostgreSQL staging data. Record the evidence and accepted limitations in the
[release record](../../src/qc_tool/database/MIGRATIONS.md#release-record).
CI success alone cannot promise zero downtime.
