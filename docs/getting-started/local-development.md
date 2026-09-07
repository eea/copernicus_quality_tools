---
title: Local development workflow
parent: Getting started
nav_order: 1
---

# Local development workflow

The supported local stack is defined in
[`docker/compose.local.yaml`](../../docker/compose.local.yaml). It deliberately
uses production-like service boundaries while enabling development-only
conveniences.

## Local services

| Service | Local implementation | Persistent data |
| --- | --- | --- |
| `userdb` | PostgreSQL 14 | `postgres_data` volume |
| `frontend` | Current checkout, Python 3.12, Django 5.2 | shared volumes and PostgreSQL |
| `worker` | Published worker image with current checkout mounted | shared volumes plus worker-local services |

The frontend is built locally. The worker image is pulled by default because
its GDAL, PostGIS, Java, and INSPIRE dependencies make it substantially more
expensive to build.

## Connect with pgAdmin

The local PostgreSQL service is published on the host loopback interface for
desktop database tools. Register a server in pgAdmin with these development
settings:

| pgAdmin field | Local value |
| --- | --- |
| Host name/address | `127.0.0.1` |
| Port | `5432` |
| Maintenance database | `qc_tool` |
| Username | `qc_user` |
| Password | `qc_password` |

The bind address is deliberately `127.0.0.1`, so PostgreSQL is not exposed to
other machines on the network. These credentials are only defaults for the
local development stack.

If port 5432 is already in use, publish PostgreSQL on another host port and use
that port in pgAdmin:

```bash
QC_TOOL_POSTGRES_HOST_PORT=55432 \
docker compose -f docker/compose.local.yaml up --detach userdb
```

The override changes only the host-facing port. Containers continue to connect
to `userdb:5432`. After changing the port or adding this mapping to an already
running stack, recreate `userdb` with the same `up --detach userdb` command.

## Common commands

```bash
# Status and logs
docker compose -f docker/compose.local.yaml ps
docker compose -f docker/compose.local.yaml logs --follow frontend
docker compose -f docker/compose.local.yaml logs --follow worker

# Django checks and shell
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage check
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage shell

# Database readiness (draft initializes models; released applies migrations)
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage makemigrations --check --dry-run
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database apply
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database check

# Restart one service after a shared-code change
docker compose -f docker/compose.local.yaml restart frontend
docker compose -f docker/compose.local.yaml restart worker
```

Local Compose enables `QC_TOOL_MIGRATE_ON_STARTUP=yes` in the development
environment. In draft it creates missing tables from models and standard roles,
with no migration files or product import. It does not alter existing tables;
use a fresh development database after schema changes. After release freeze
it applies committed migrations; production uses an explicit deployment job. See [Database migrations](../development/database-migrations.md).

Moving from a draft or incompatible legacy schema to a released schema requires
a new database initialized from the frozen migrations. Preserve needed local
data and use a new database/volume; import retained records through an explicit
conversion procedure. Startup does not perform that transfer.

## Create a local administrator

The default local stack already creates `admin`. If demo bootstrapping is
disabled, create an administrator interactively so the password does not appear
in shell history:

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage createsuperuser
```

There is no public registration endpoint. Application administrators create
and manage users through Django Admin.

## Override local settings

Compose substitutions may be set in the shell or in a developer-owned env
file. Do not commit secrets.

```bash
QC_TOOL_PORT=8080 \
QC_TOOL_PLATFORM=linux/amd64 \
docker compose -f docker/compose.local.yaml up --detach
```

Frequently useful substitutions include:

| Variable | Local default | Effect |
| --- | --- | --- |
| `QC_TOOL_PORT` | `8000` | Host port bound to `127.0.0.1` |
| `QC_TOOL_PLATFORM` | `linux/amd64` | Container platform |
| `QC_TOOL_SOURCE_VERSION` | `master` | Upstream GitHub ref downloaded during frontend build |
| `QC_TOOL_IMAGE_TAG` | `dev` for frontend, `2.4.6` for worker | Image tag substitution |
| `QC_TOOL_POSTGRES_DB` | `qc_tool` | Local user database name |
| `QC_TOOL_POSTGRES_USER` | `qc_user` | Local user database role |
| `QC_TOOL_POSTGRES_PASSWORD` | `qc_password` | Development-only DB password |
| `QC_TOOL_POSTGRES_HOST_PORT` | `5432` | PostgreSQL port published on `127.0.0.1` for desktop tools |
| `S3_ALLOWED_ENDPOINTS` | empty | Exact HTTPS S3 origins; empty disables S3 |
| `LEAVE_SCHEMA` | `no` | Retain worker job schema for debugging |
| `LEAVE_JOBDIR` | `no` | Retain worker job directory for debugging |

`QC_TOOL_IMAGE_TAG` is reused in two image names. Setting it overrides both the
local frontend tag and the published worker tag, so use it only when matching
tags exist for both. `QC_TOOL_SOURCE_VERSION` must exist in the upstream GitHub
repository; the runtime bind mount does not remove that build-time requirement.

## Source ownership boundaries

Keep changes in the layer that owns the behavior:

- user identity, roles, permissions, credentials, and grants belong in
  `frontend/accounts/`;
- deliveries, jobs, dashboard access, HTTP routes, and browser workflows belong
  in `frontend/dashboard/`;
- queue polling and QC job execution belong in `worker/`;
- reusable archive, S3, product-definition, and worker-authentication policies
  belong in their small top-level security packages;
- product recipes belong in `product_definitions/`;
- specific QC algorithms belong in `raster/` or `vector/`.

Product recipes and raster/vector check behavior are domain changes. Keep them
separate from infrastructure, authentication, or documentation refactors and
run the appropriate specialist regression suite.

## Rebuild versus restart

| Change | Action |
| --- | --- |
| Django Python, templates | Usually automatic reload; restart frontend if needed |
| Browser JS/CSS | Hard-refresh the browser |
| Worker or shared Python | Restart worker |
| Frontend requirements or Dockerfile | Rebuild frontend |
| Worker system/Python dependencies | Rebuild worker; expect a long build |
| Compose environment or volume mapping | Recreate affected service with `up --detach` |

See [Testing](../development/testing.md) before opening a pull request.
