#!/bin/sh

# This script resides at /etc/my_init.d and starts ui and wps services.

python3 -m qc_tool.frontend.manage runserver 0.0.0.0:8000 &

python3 -m qc_tool.wps.server &
