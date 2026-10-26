#!/usr/bin/env bash
# Run against packaged source, fresh storage and a private disposable database.
set -euo pipefail

: "${TEST_IMAGE:?Set TEST_IMAGE to the built frontend image}"
smoke_storage_mode="${STORAGE_MODE:-volume}"
case "$smoke_storage_mode" in volume|bind) ;; *) echo 'STORAGE_MODE must be volume or bind.' >&2; exit 2 ;; esac
smoke_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
smoke_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/qc-tool-browser.XXXXXX")"
smoke_name="qc-tool-browser-$(basename "$smoke_temp_dir" | tr '[:upper:]' '[:lower:]')"
smoke_container_id=""
smoke_volume_created=no
export QC_TOOL_BROWSER_ARTIFACTS_DIR="${QC_TOOL_BROWSER_ARTIFACTS_DIR:-$smoke_temp_dir/artifacts}"
mkdir -p "$QC_TOOL_BROWSER_ARTIFACTS_DIR"

cleanup() {
  smoke_result=$?
  trap - EXIT
  if [ -n "$smoke_container_id" ]; then
    docker logs "$smoke_container_id" >"$QC_TOOL_BROWSER_ARTIFACTS_DIR/frontend.log" 2>&1 || true
    docker rm --force "$smoke_container_id" >/dev/null || true
  fi
  if [ "$smoke_volume_created" = yes ]; then
    docker volume rm "$smoke_name" >/dev/null || true
  fi
  # Artifacts are intentionally retained outside the checkout for failure review.
  echo "Browser smoke artifacts: $QC_TOOL_BROWSER_ARTIFACTS_DIR"
  exit "$smoke_result"
}
trap cleanup EXIT

if [ "$smoke_storage_mode" = volume ]; then
  docker volume create "$smoke_name" >/dev/null
  smoke_volume_created=yes
  smoke_mount="type=volume,source=$smoke_name,target=/tmp/qc-tool-upload-mount"
else
  mkdir "$smoke_temp_dir/upload-mount"
  smoke_mount="type=bind,source=$smoke_temp_dir/upload-mount,target=/tmp/qc-tool-upload-mount"
fi

# No existing host application path is mounted. INCOMING_DIR is deliberately
# absent: uploading must provision its leaf below the already-mounted parent.
smoke_container_id="$(docker create --init --name "$smoke_name" \
  --publish 127.0.0.1::8000 \
  --tmpfs /tmp/qc-tool-browser:rw,size=1g \
  --mount "$smoke_mount" \
  --env QC_TOOL_ENVIRONMENT=test \
  --env DB_ENGINE=sqlite \
  --env DJANGO_SECRET_KEY=disposable-browser-test-secret \
  --env DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost \
  --env FRONTEND_DB_PATH=/tmp/qc-tool-browser/frontend.sqlite3 \
  --env WORK_DIR=/tmp/qc-tool-browser/work \
  --env INCOMING_DIR=/tmp/qc-tool-upload-mount/incoming \
  --env BOUNDARY_DIR=/tmp/qc-tool-upload-mount/boundaries \
  --env PRODUCT_DIRS=/tmp/qc-tool-browser/empty-product-definitions \
  --env REFRESH_JOB_STATUSES_BACKGROUND=no \
  --env UPDATE_JOB_STATUSES=no \
  "$TEST_IMAGE" bash -euc '
    python3 -m qc_tool.frontend.manage database apply
    python3 /tmp/qc-tool-browser-bootstrap.py
    exec /run_frontend.sh
  ')"
docker cp "$smoke_script_dir/bootstrap.py" "$smoke_container_id:/tmp/qc-tool-browser-bootstrap.py"
docker start "$smoke_container_id" >/dev/null
smoke_port="$(docker port "$smoke_container_id" 8000/tcp | sed -n 's/^127\.0\.0\.1://p')"
export QC_TOOL_BROWSER_BASE_URL="http://127.0.0.1:$smoke_port"

smoke_ready=no
for ((attempt = 0; attempt < 90; attempt++)); do
  if curl --fail --silent "$QC_TOOL_BROWSER_BASE_URL/accounts/login/" >/dev/null; then
    smoke_ready=yes
    break
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "$smoke_container_id")" != true ]; then
    docker logs "$smoke_container_id" >&2
    exit 1
  fi
  sleep 1
done
if [ "$smoke_ready" != yes ]; then
  echo 'Disposable browser frontend did not become ready.' >&2
  exit 1
fi
docker exec "$smoke_container_id" test ! -e /tmp/qc-tool-upload-mount/incoming
# docker cp cannot read every Docker tmpfs implementation (including Desktop).
docker exec "$smoke_container_id" tar -C /tmp/qc-tool-browser -cf - fixtures | LC_ALL=C tar -C "$smoke_temp_dir" -xf -
export QC_TOOL_BROWSER_FIXTURES="$smoke_temp_dir/fixtures"
npm --prefix "$smoke_script_dir" test
docker exec "$smoke_container_id" test -d /tmp/qc-tool-upload-mount/incoming
