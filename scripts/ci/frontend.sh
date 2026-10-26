#!/usr/bin/env bash
# Run the same packaged frontend checks locally and in CI, without host data.
set -euo pipefail
: "${TEST_IMAGE:?Set TEST_IMAGE to the frontend image built from this checkout}"

run_frontend() {
    docker run --rm --init --network "${CI_DOCKER_NETWORK:-host}" \
        --workdir /usr/local/src/copernicus_quality_tools \
        --env QC_TOOL_ENVIRONMENT="${QC_TOOL_ENVIRONMENT:-test}" \
        --env DJANGO_SECRET_KEY=ci-production-only-3xJw7pL9vK2qN8mR5tY1uB6cD4eF0gHsZa \
        --env DJANGO_ALLOWED_HOSTS="${DJANGO_ALLOWED_HOSTS:-testserver,localhost}" \
        --env DB_ENGINE="${DB_ENGINE:-sqlite}" \
        --env POSTGRES_DB=qc_tool_schema_ci \
        --env POSTGRES_USER=qc_tool_ci \
        --env POSTGRES_PASSWORD=ci-only-postgres-password \
        --env POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}" \
        --env POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
        --env WORK_DIR=/tmp/qc-tool-work \
        --env FRONTEND_DB_PATH=/tmp/qc-tool-test.sqlite3 \
        --env INCOMING_DIR=/tmp/qc-tool-incoming \
        --env BOUNDARY_DIR=/tmp/qc-tool-boundaries \
        --env PRODUCT_DIRS=/usr/local/src/copernicus_quality_tools/product_definitions \
        --env DJANGO_SECURE_SSL_REDIRECT="${DJANGO_SECURE_SSL_REDIRECT:-no}" \
        --env DJANGO_TRUST_PROXY_SSL_HEADER="${DJANGO_TRUST_PROXY_SSL_HEADER:-no}" \
        --env DJANGO_SECURE_HSTS_SECONDS="${DJANGO_SECURE_HSTS_SECONDS:-0}" \
        --env DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS="${DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS:-no}" \
        --env DJANGO_SECURE_HSTS_PRELOAD="${DJANGO_SECURE_HSTS_PRELOAD:-no}" \
        "$TEST_IMAGE" "$@"
}

case "${1:-}" in
    runtime)
        run_frontend python3 scripts/ci/frontend_runtime.py
        # Import first: a missing shipped dependency must fail, never skip.
        run_frontend python3 -m unittest scripts.tests.deployment.test_frontend_entrypoint -v
        ;;
    database)
        case "${DB_ENGINE:-}" in
            sqlite|postgres) ;;
            *) echo 'Set DB_ENGINE to sqlite or postgres' >&2; exit 2 ;;
        esac
        # One container retains SQLite's schema across these commands. The schema
        # probe refuses nonempty targets; PostgreSQL must also be disposable.
        run_frontend bash -euc '
            python3 -m qc_tool.database.checks.schema
            python3 -m qc_tool.frontend.manage check
            python3 -m qc_tool.frontend.manage database check
            python3 -m qc_tool.frontend.manage collectstatic --noinput
            python3 -m qc_tool.frontend.manage test \
                qc_tool.frontend.accounts.tests \
                qc_tool.frontend.dashboard.services.tests \
                qc_tool.frontend.dashboard.tests \
                qc_tool.database.tests.integration \
                qc_tool.test.test_uploaded_product_definitions --verbosity 2
        '
        ;;
    deployment)
        export QC_TOOL_ENVIRONMENT=production DJANGO_ALLOWED_HOSTS=qc-tool.example.test
        export DJANGO_SECURE_SSL_REDIRECT=yes DJANGO_TRUST_PROXY_SSL_HEADER=yes
        export DJANGO_SECURE_HSTS_SECONDS=31536000
        export DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=yes DJANGO_SECURE_HSTS_PRELOAD=yes
        run_frontend python3 -m qc_tool.frontend.manage check --deploy --fail-level WARNING
        ;;
    *) echo 'Usage: bash scripts/ci/frontend.sh runtime|database|deployment' >&2; exit 2 ;;
esac
