---
title: Startup troubleshooting
parent: Getting started
nav_order: 2
---

# Startup troubleshooting

Start with service state and recent logs:

```bash
docker compose -f docker/compose.local.yaml ps
docker compose -f docker/compose.local.yaml logs --tail 200 frontend worker userdb
```

## Port 8000 is already in use

Choose another local port:

```bash
QC_TOOL_PORT=8080 docker compose -f docker/compose.local.yaml up --detach
```

Then open <http://localhost:8080/accounts/login/>.

## Port 5432 is already in use

Choose another host port for pgAdmin and other desktop database clients:

```bash
QC_TOOL_POSTGRES_HOST_PORT=55432 \
docker compose -f docker/compose.local.yaml up --detach userdb
```

Connect pgAdmin to `127.0.0.1:55432`. Do not change the frontend's
`POSTGRES_PORT`; container-to-container traffic continues to use
`userdb:5432`.

## Frontend waits for PostgreSQL

Inspect the database health check:

```bash
docker compose -f docker/compose.local.yaml ps userdb
docker compose -f docker/compose.local.yaml logs userdb
```

If you changed `QC_TOOL_POSTGRES_DB`, `QC_TOOL_POSTGRES_USER`, or
`QC_TOOL_POSTGRES_PASSWORD`, use the same values for the whole Compose project.
Existing database volumes retain the credentials used when they were created.

For an intentional clean reset, stop the stack and remove its volumes. This
deletes all local QC Tool state:

```bash
docker compose -f docker/compose.local.yaml down --volumes
```

## Worker remains unhealthy

The full INSPIRE validator has a long startup period, especially on ARM hosts
using `linux/amd64` emulation. Follow the worker logs before assuming it failed:

```bash
docker compose -f docker/compose.local.yaml logs --follow worker
```

The worker health check requires both its internal HTTP service and the
configured validator to answer.

## Delivery uploads report unavailable storage

A Docker named volume supports uploads; switching to a bind mount is not a
requirement. Check the configured path, mount, permissions and free space first.
Use the same Compose files, environment file and project name as the running
stack; the commands below use the local Compose configuration.

### Check the mount root and upload directory

The local and EEA Compose files use this layout in both frontend and worker:

```text
/mnt/qc_tool_incoming/             # mounted volume root
└── incoming/                     # INCOMING_DIR; Django MEDIA_ROOT
    └── <username>/               # per-user delivery files and upload chunks
```

`qc_tool_incoming` is mounted at `/mnt/qc_tool_incoming`, while uploads go to
`/mnt/qc_tool_incoming/incoming`. A bind mount at the same target has the same
layout: its host source is the parent of `incoming/`. Mounting a host directory
does not itself create this child or grant the container write access. If you
instead mount directly at `/mnt/qc_tool_incoming/incoming`, the host source is
already the upload root; do not add another `incoming/` inside it. Give frontend
and worker the same persistent source and mount target. Confirm the effective
Compose configuration:

```bash
docker compose -f docker/compose.local.yaml config
docker compose -f docker/compose.local.yaml exec frontend \
  sh -c 'ls -ldn /mnt/qc_tool_incoming "$INCOMING_DIR"'
```

Current QC Tool creates an absent `incoming` leaf with mode `0750` on the first
upload POST, provided its parent already exists and is writable. Chunk-check
GET requests create nothing; a `404` for a chunk not yet uploaded is expected.
Missing ancestors remain a storage error.

Source revision `e2e52a5` has the missing-directory bug: both chunk-check GETs
and upload POSTs require the configured upload root to exist and otherwise
return `503` with “Upload storage is unavailable.” Automatic leaf creation was
added in `672e8769`. For the older revision, provision only the configured
`incoming/` leaf on the verified volume with the frontend's runtime ownership
and restricted permissions, or deploy an image containing the fix through the
normal release procedure. Changing to a bind mount is unnecessary for this bug.

Check the actual running image as well as the checkout revision. At `e2e52a5`,
the EEA Compose file selects prebuilt `2.4.7rc4` frontend/worker images without
a source-code bind mount; checking out another commit does not replace their
application code. Local Compose binds the checkout into the containers, while
their dependencies still come from their images. Record the effective source
mounts and running image tag/digest when reporting the problem.

For the guarded Azure/EEA layout, follow
[EEA persistent storage](../deployment/eea-storage.md) instead: verify the real
host mount, identity marker and preprovisioned application directories before
startup. Do not create a missing mount parent, replace the marker or create a
local fallback directory to bypass the guard.

### Check runtime permissions and capacity

Check the frontend and worker runtime UID/GID, including any Compose `user`
override:

```bash
docker compose -f docker/compose.local.yaml exec frontend id
docker compose -f docker/compose.local.yaml exec worker id
docker compose -f docker/compose.local.yaml exec frontend \
  df -h /mnt/qc_tool_incoming /tmp
docker compose -f docker/compose.local.yaml exec frontend \
  df -i /mnt/qc_tool_incoming /tmp
```

The frontend needs traversal access through the parent directories and write
access to incoming storage; workers must be able to read the resulting delivery
files. Provision ownership and restricted modes for those actual runtime
identities. Do not use blanket `chmod 777` or recursively change database-volume
ownership. A read-only mount also prevents uploads even when directory mode
bits appear writable.

Check free bytes, free inodes and any storage quota. Chunk staging and the
assembled ZIP can coexist, so allow space beyond the final delivery size. Also
check the frontend's multipart spool: `QC_TOOL_UPLOAD_TEMP_DIR` if configured,
otherwise its operating-system temporary directory, normally `/tmp`. Replace
`/tmp` in the checks above when using a custom spool path. Space available on
incoming storage does not establish that the spool has room.

In recent images, `upload_storage_unavailable` (`503`) identifies missing,
inaccessible or read-only upload-root storage; `upload_storage_full` (`507`)
identifies a space or quota failure detected there. Other chunk or assembly I/O
failures can return `upload_storage_error`. Inspect the frontend logs for the
underlying filesystem error rather than inferring the cause from a generic
browser message. Keep logs and Compose output private or redact secrets before
sharing them.

Boundary ZIP uploads use `BOUNDARY_DIR` and their own validation/extraction
workflow. If those fail while delivery uploads work, check boundary storage and
the multipart spool separately; changing the incoming mount does not repair
either location. See [Storage access](../deployment/storage-access.md) for the
application's storage locations.

## Source edits do not appear

Confirm the Compose project was started from the repository root and that the
checkout bind mount is present:

```bash
docker compose -f docker/compose.local.yaml config
```

Restart the affected service. Rebuild if a dependency or Dockerfile changed.

```bash
docker compose -f docker/compose.local.yaml restart frontend worker
```

## Login does not work

The development users are only created when both
`QC_TOOL_BOOTSTRAP_DEMO_USERS=yes` and a development/test environment are set.
Check frontend startup logs, or create an administrator interactively:

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage createsuperuser
```

If case-insensitive usernames are enabled, duplicate usernames that differ only
by case fail closed. Resolve the duplicate records rather than weakening the
authentication backend.

## S3 registration is unavailable

S3 is disabled when `S3_ALLOWED_ENDPOINTS` is empty. Configure exact canonical
HTTPS origins in both frontend and worker environments. Do not use wildcards,
embedded credentials, paths, query strings, or HTTP endpoints.

## A private data request returns 401 or 403

- `401` means the session or machine credential is missing or expired.
- `403` means authentication succeeded but the required permission, ownership,
  or product scope is missing.

Browser pages redirect anonymous users to login. Session-backed JSON endpoints
return JSON errors so the browser can redirect without treating login HTML as
API data.

## Escalating a problem

Include:

- the current Git commit or image tag;
- host architecture and Docker versions;
- the exact command used;
- affected service status;
- relevant logs with passwords, API credentials, worker tokens, S3 secrets,
  and user data removed.

Do not attach database dumps or delivery archives to a public issue.
