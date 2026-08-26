#!/bin/sh
set -eu

cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend

# Create frontend database and tables if they do not exist.
python3 -m qc_tool.frontend.manage migrate --noinput
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
        --group product_manager \
        --product clms_ua_lcuc_c2021-2024_v010ha
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
