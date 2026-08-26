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

The checkout is mounted read-only in the local containers. Migration drift
checks work, but generating a migration file requires a writable environment.
Do not bypass this by editing generated migration state blindly.

## Frontend regression suite

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage test \
    qc_tool.frontend.accounts.tests \
    qc_tool.frontend.dashboard.services.tests \
    qc_tool.frontend.dashboard.tests
```

These explicit package labels include both dashboard test packages while
avoiding the historical `dashboard/tests.py` discovery-name collision.

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
