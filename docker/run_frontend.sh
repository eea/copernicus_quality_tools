#!/bin/sh

# Exit on failed commands or unset variables so initialization cannot continue
# with a partially migrated database.
set -eu

cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend

# Create frontend database and tables if they do not exist.
python3 -m qc_tool.frontend.manage migrate

# Create default user accounts.
python3 -m qc_tool.frontend.manage create_default_user --username admin --password admin --superuser
python3 -m qc_tool.frontend.manage create_default_user --username guest --password guest
python3 -m qc_tool.frontend.manage create_default_user --username guest2 --password guest2
python3 -m qc_tool.frontend.manage create_default_user --username guest3 --password guest3

# Start Django's auto-reloading development server. Debug mode remains opt-in so
# a missing IDE connection never blocks normal startup or the healthcheck.
if [ "${QC_TOOL_DEBUG:-no}" = "yes" ]; then
    exec python3 -m debugpy \
        --listen "0.0.0.0:${QC_TOOL_DEBUG_PORT:-5678}" \
        -m qc_tool.frontend.manage runserver 0.0.0.0:8000
fi

exec python3 -m qc_tool.frontend.manage runserver 0.0.0.0:8000
