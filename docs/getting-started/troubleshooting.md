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
  or product/region scope is missing.

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
