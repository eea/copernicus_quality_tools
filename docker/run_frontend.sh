#!/bin/sh
set -eu

cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend

# Validate runtime topology before touching schema or static storage. Multiple
# WSGI processes duplicate the application-owned refresh loop; scaling requires
# moving that service out of WSGI first.
if [ "${QC_TOOL_WEB_WORKERS:-1}" != "1" ]; then
    echo "QC_TOOL_WEB_WORKERS must be 1 until the background refresh service supports multiple frontend processes." >&2
    exit 1
fi
validate_development_option() {
    startup_option_name="$1"
    startup_option_value="$2"
    case "$startup_option_value" in
        yes|no) ;;
        *) echo "$startup_option_name must be yes or no." >&2; exit 1 ;;
    esac
    if [ "$startup_option_value" = "yes" ]; then
        case "${QC_TOOL_ENVIRONMENT:-production}" in
            development|test) ;;
            *)
                echo "Refusing development startup option $startup_option_name outside development/test." >&2
                exit 1
                ;;
        esac
    fi
}
validate_development_option QC_TOOL_BOOTSTRAP_DEMO_USERS "${QC_TOOL_BOOTSTRAP_DEMO_USERS:-no}"
validate_development_option QC_TOOL_DEV_SERVER "${QC_TOOL_DEV_SERVER:-no}"

# Production initialization is an explicit operator command. Startup checks a
# restored/current schema without changing its records or permissions.
if [ -n "${QC_TOOL_MIGRATE_ON_STARTUP+x}" ]; then
    echo "QC_TOOL_MIGRATE_ON_STARTUP is unsupported. Use QC_TOOL_INITIALIZE_ON_STARTUP for local initialization." >&2
    exit 1
fi
case "${QC_TOOL_INITIALIZE_ON_STARTUP:-no}" in
    yes)
        case "${QC_TOOL_ENVIRONMENT:-production}" in
            development|test) ;;
            *)
                echo "Automatic initialization is limited to development/test. Initialize an empty production database explicitly or restore a prepared copy." >&2
                exit 1
                ;;
        esac
        ;;
    no) ;;
    *)
        echo "QC_TOOL_INITIALIZE_ON_STARTUP must be yes or no." >&2
        exit 1
        ;;
esac
if startup_database_mode="$(python3 -m qc_tool.frontend.manage database check --allow-maintenance-recovery)"; then
    :
else
    startup_database_status="$?"
    if [ "${QC_TOOL_INITIALIZE_ON_STARTUP:-no}" = "yes" ] && [ "$startup_database_status" = "1" ]; then
        python3 -m qc_tool.frontend.manage database apply
        startup_database_mode="$(python3 -m qc_tool.frontend.manage database check --allow-maintenance-recovery)"
    else
        echo "Database is not ready. Restore a matching copy or explicitly initialize an empty target. Existing databases are never upgraded or reset." >&2
        exit 1
    fi
fi
case "$startup_database_mode" in
    ready|maintenance-recovery) ;;
    *) echo "Database startup returned an unsupported readiness state." >&2; exit 1 ;;
esac
python3 -m qc_tool.frontend.manage collectstatic --noinput

# Predictable demo credentials are opt-in and validated before any startup work.
if [ "${QC_TOOL_BOOTSTRAP_DEMO_USERS:-no}" = "yes" ] && [ "$startup_database_mode" = "ready" ]; then
    python3 -m qc_tool.frontend.manage create_default_user --username admin --password admin --superuser
    python3 -m qc_tool.frontend.manage create_default_user --username guest --password guest
    python3 -m qc_tool.frontend.manage create_default_user \
        --username product_manager \
        --password product_manager \
        --group product_manager
fi

if [ "${QC_TOOL_DEV_SERVER:-no}" = "yes" ] && [ "$startup_database_mode" = "ready" ]; then
    exec python3 -m qc_tool.frontend.manage runserver 0.0.0.0:8000
fi

# The current WSGI module owns one background status-refresh loop. Keep one
# process until that loop is moved to a dedicated service. Threads let browsing
# continue during large uploads; timeout monitors worker health, not a request's
# duration with gthread. Browser and ingress upload deadlines remain separate.
exec gunicorn \
    --bind 0.0.0.0:8000 \
    --workers "${QC_TOOL_WEB_WORKERS:-1}" \
    --worker-class gthread \
    --threads 4 \
    --timeout "${QC_TOOL_WEB_TIMEOUT_SECONDS:-120}" \
    qc_tool.frontend.wsgi:application
