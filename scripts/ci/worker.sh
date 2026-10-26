#!/usr/bin/env bash
# Keep the large worker image and its full QC regression suite on one runner.
set -euo pipefail
: "${TEST_WORKER_IMAGE:?Set TEST_WORKER_IMAGE to the worker built from this checkout}"
docker run --rm --init \
    --workdir /usr/local/src/copernicus_quality_tools \
    --env SKIP_INSPIRE_CHECK=yes --env RUN_INSPIRE_VALIDATOR=no \
    --env QC_TOOL_ENVIRONMENT=test \
    --env WORK_DIR=/tmp/qc-tool-worker-work \
    --env INCOMING_DIR=/tmp/qc-tool-worker-incoming \
    --env BOUNDARY_DIR=/tmp/qc-tool-worker-boundaries \
    "$TEST_WORKER_IMAGE" sh -euc '
        pg_ctlcluster 17 main start
        python3 docker/check_worker_runtime.py
        python3 -m pip check
        python3 -c "import supervisor"
        python3 -m unittest scripts.tests.deployment.test_worker_entrypoint -v
        python3 -m unittest discover qc_tool.test -v
    '
