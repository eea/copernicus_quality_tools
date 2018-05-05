#!/bin/sh

# This is a helper script starting docker container running qc tool ui and wps.
# This script requires two arguments. The first argument is the parent dir of
# the code directory. The second argument is the directory with testing data
# example run: sh ./run_docker_local.sh /home/jiri/github /home/jiri/github/copernicus_quality_tools/testing_data

hostbase_dir=${hostbase_dir:-$1}
host_incoming_dir=$2

host=${host:-172.17.0.2}
WPS_PORT=5000
WPS_URL=http://$host:$WPS_PORT/wps
WPS_DIR=/mnt/wps
WPS_OUTPUT_URL=http://$host:$WPS_PORT/output
UI_PORT=8000
INCOMING_DIR=/mnt/wps/data
docker run --rm \
  --publish $WPS_PORT:$WPS_PORT \
  --publish $UI_PORT:$UI_PORT \
  --volume $hostbase_dir/copernicus_quality_tools:/usr/local/src/copernicus_quality_tools \
  --volume $hostbase_dir/wps:$WPS_DIR \
  --volume $host_incoming_dir:$INCOMING_DIR \
  --env WPS_DIR=$WPS_DIR \
  --env WPS_PORT=$WPS_PORT \
  --env WPS_URL=$WPS_URL \
  --env WPS_URL=$WPS_URL \
  --env WPS_OUTPUT_URL=$WPS_OUTPUT_URL \
  --env INCOMING_DIR=$INCOMING_DIR \
  --env PYTHONPATH=/usr/local/src/copernicus_quality_tools/src \
  ubucop
