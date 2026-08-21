#!/bin/sh

cd /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend

# Create frontend database and tables if they do not exist.
python3 -m qc_tool.frontend.manage migrate

# Create default user accounts.
python3 -m qc_tool.frontend.manage create_default_user --username admin --password admin --superuser
python3 -m qc_tool.frontend.manage create_default_user --username guest --password guest
python3 -m qc_tool.frontend.manage create_default_user --username guest2 --password guest2
python3 -m qc_tool.frontend.manage create_default_user --username guest3 --password guest3

# Start Django development server.
python3 -m qc_tool.frontend.manage runserver 0.0.0.0:8000
