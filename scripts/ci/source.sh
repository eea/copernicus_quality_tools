#!/usr/bin/env bash
# Shared checks run once, before expensive image builds.
set -euo pipefail

export PYTHONPATH=src
python3 -m unittest qc_tool.database.tests.test_source
python3 -m qc_tool.database.checks.source
node --test src/qc_tool/frontend/dashboard/tests/javascript/*.test.cjs

# Configuration validation only: these commands never start deployment services.
export QC_TOOL_FRONTEND_IMAGE=qc-tool-frontend-ci:configuration-only
export QC_TOOL_WORKER_IMAGE=qc-tool-worker-ci:configuration-only
export QC_TOOL_POSTGRES_PASSWORD=ci-only-configuration-check-password
export DJANGO_SECRET_KEY=ci-only-configuration-check-secret
export QC_TOOL_PERSISTENT_ROOT=/srv/qc-tool-ci-configuration-only
export QC_TOOL_PERSISTENT_STORAGE_ID=ci-only-storage-identity
docker compose -f docker/compose.local.yaml config --quiet
docker compose -f docker/docker-compose.eea.yml config --quiet
docker compose -f docker/docker-compose.eea.yml -f docker/compose.eea-storage.yaml config --quiet
docker compose -f docker/docker-compose.service_provider.yml config --quiet
