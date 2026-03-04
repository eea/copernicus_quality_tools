#!/bin/bash
# Usage: ./start_optional_postgres.sh [SERVICE_NAME] [ACTUAL_COMMAND...]

SERVICE_NAME=$1
shift # Remove service name from arguments

if [ "$RUN_POSTGRES" = "no" ]; then
    echo "Service $SERVICE_NAME is DISABLED via environment variable."
    # We sleep infinity to satisfy supervisord's 'startsecs' and 'autorestart'
    exec sleep infinity
else
    echo "Service $SERVICE_NAME is ENABLED. Starting..."
    exec "$@"
fi