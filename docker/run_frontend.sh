#!/bin/sh
set -eu

cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend

# Production schema changes belong to one explicit deployment job, using the
# same release image as the web process. Startup only verifies readiness.
case "${QC_TOOL_MIGRATE_ON_STARTUP:-no}" in
    yes)
        case "${QC_TOOL_ENVIRONMENT:-production}" in
            development|test) ;;
            *)
                echo "Automatic migrations are limited to development/test. Run database apply as a deployment job." >&2
                exit 1
                ;;
        esac
        python3 -m qc_tool.frontend.manage database apply
        ;;
    no) ;;
    *)
        echo "QC_TOOL_MIGRATE_ON_STARTUP must be yes or no." >&2
        exit 1
        ;;
esac
if ! python3 -m qc_tool.frontend.manage database check; then
    echo "Database is not ready. Draft: initialize a fresh development schema. Released: apply committed migrations. See src/qc_tool/database/MIGRATIONS.md." >&2
    exit 1
fi
python3 -m qc_tool.frontend.manage collectstatic --noinput

# Predictable demo credentials are opt-in and must never be enabled in a
# production deployment.
if [ "${QC_TOOL_BOOTSTRAP_DEMO_USERS:-no}" = "yes" ]; then
    case "${QC_TOOL_ENVIRONMENT:-production}" in
        development|test) ;;
        *)
            echo "Refusing to create predictable demo users outside development/test." >&2
            exit 1
            ;;
    esac
    python3 -m qc_tool.frontend.manage create_default_user --username admin --password admin --superuser
    python3 -m qc_tool.frontend.manage create_default_user --username guest --password guest
    python3 -m qc_tool.frontend.manage create_default_user \
        --username product_manager \
        --password product_manager \
        --group product_manager
fi

if [ "${QC_TOOL_DEV_SERVER:-no}" = "yes" ]; then
    exec python3 -m qc_tool.frontend.manage runserver 0.0.0.0:8000
fi

# The current WSGI module owns one background status-refresh loop. Keep one
# process by default until that loop is moved to a dedicated service.
exec gunicorn \
    --bind 0.0.0.0:8000 \
    --workers "${QC_TOOL_WEB_WORKERS:-1}" \
    --timeout "${QC_TOOL_WEB_TIMEOUT_SECONDS:-120}" \
    qc_tool.frontend.wsgi:application
