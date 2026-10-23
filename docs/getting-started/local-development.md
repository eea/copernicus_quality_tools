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
| `worker` | Current checkout, locally built Python 3.12/geospatial runtime | shared volumes plus worker-local services |

Both application images build locally from this checkout. The first worker
build is substantially more expensive because it compiles GDAL and Squid and
includes PostGIS, Java and INSPIRE. The frontend-only preview below does not
start or build the worker.

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

# Read-only schema inspection (never changes existing tables)
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database plan
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database check

# Explicit initialization: only for a confirmed entirely empty target
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage database apply

# Restart one service after a shared-code change
docker compose -f docker/compose.local.yaml restart frontend
docker compose -f docker/compose.local.yaml restart worker
```

Local Compose enables `QC_TOOL_INITIALIZE_ON_STARTUP=yes` in the development
environment. It initializes an entirely empty database from current models and
standard roles, without importing products. A complete matching database is
left unchanged; partial or foreign schemas and detected model drift are refused.
Use a new separate development target after model schema changes, preserving any data you
still need. Startup never upgrades or resets an existing database.

v3.0.0 contains no migration framework, definitions, snapshots or legacy
converter. See [Database initialization](../development/database-migrations.md).

The initial product catalog is empty. Add reviewed JSON specifications through
**Products → Upload specification** as an administrator, then assign their
products to users. Keeping recipe files in `product_definitions/` or `PRODUCT_DIRS`
does not add them to the catalog, QC selector, or product-grant choices. Local
demo accounts start without product assignments; restarts retain existing
accounts and catalog data.

Existing legacy data is converted manually outside the codebase into a prepared
current-schema artifact. Follow the
[manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md) before using
that copy. Preserve needed data before selecting new volumes; startup does not
transfer it.

## Preview current models in a separate local project

If Admin reports a missing `qc_database_transfer_receipt` table after a model
change, the retained database has an earlier draft schema. Restarting cannot
upgrade it, and `database apply` refuses an occupied incompatible database.
Preserve that database and use a separate empty development target to inspect
the current Admin interface.

Choose an unused project name and unused host ports. Run from the repository
root, keeping this function for every preview command:

```bash
QC_TOOL_PREVIEW_PROJECT=qc-tool-schema-preview-20261021

qc_preview() {
  QC_TOOL_PORT=8001 \
  QC_TOOL_POSTGRES_HOST_PORT=5433 \
  QC_TOOL_POSTGRES_DB=qc_tool_schema_preview \
  docker compose --project-name "$QC_TOOL_PREVIEW_PROJECT" \
    -f docker/compose.local.yaml "$@"
}

# Read-only: validate the separate configuration before starting anything.
qc_preview config --quiet

# Start only the new PostgreSQL instance and frontend, using cached images.
qc_preview up --detach --wait userdb
qc_preview up --detach --wait --no-build --pull never frontend

# Confirm the new schema is ready.
qc_preview exec frontend python3 -m qc_tool.frontend.manage database check
```

The frontend command requires an existing compatible local frontend image.
The read-only source mount supplies current Python/templates and the current
startup script. If that image is absent, or its Dockerfile/runtime dependencies
have changed, run `qc_preview build frontend`, then repeat the frontend `up`
command. This builds only the frontend. The PostgreSQL command may pull its
standard image if it is not cached.

Open <http://localhost:8001/admin/database/> and sign in with the new local
development account (`admin` / `admin`). A separate browser profile or private
window keeps its session apart from the original localhost installation.
Development startup initializes this entirely empty database and creates the
demo accounts. No worker runs, so this preview supports Admin inspection rather
than QC job execution.

The unique Compose project isolates **all six named volumes**, including the
database, work/maintenance state, boundaries, incoming files, submissions and
frontend storage. The original project, its database and files, and its
localhost:8000 listener remain untouched. Database credentials keep their normal
local configuration; no checked-in settings or source copying are required.
Changing only `QC_TOOL_POSTGRES_DB` on the original project does not create a
fresh PostgreSQL cluster or isolate its other storage.

This preview contains no retained users, products or job history. Keeping those
records requires a separately prepared and verified current-schema handoff,
with its matching files; restoring an old-schema dump reproduces the mismatch.
Follow the [manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md)
when such an archive is available, restoring its schema into an empty target
before any initialization. Do not add the missing table manually or remove the
original volumes to clear the error. Use another unused project name after
future model changes rather than resetting a retained preview.

To stop the preview while preserving its data:

```bash
qc_preview down
```

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
docker compose -f docker/compose.local.yaml up --detach
```

Frequently useful substitutions include:

| Variable | Local default | Effect |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `copernicus-quality-tools-local` | Selects the local project and its named volumes; a new unused name isolates the whole installation |
| `QC_TOOL_PORT` | `8000` | Host port bound to `127.0.0.1` |
| `DOCKER_DEFAULT_PLATFORM` | Docker host architecture | Optional explicit platform for native builds or deliberate emulation |
| `QC_TOOL_PLATFORM` | unset | Explicit platform when adding `-f docker/compose.platform.yaml` |
| `QC_TOOL_SOURCE_VERSION` | `development` | Provenance label for images built from this checkout |
| `QC_TOOL_IMAGE_TAG` | `dev` | Matching locally built frontend and worker image tags |
| `QC_TOOL_POSTGRES_DB` | `qc_tool` | Local user database name |
| `QC_TOOL_POSTGRES_USER` | `qc_user` | Local user database role |
| `QC_TOOL_POSTGRES_PASSWORD` | `qc_password` | Development-only DB password |
| `QC_TOOL_POSTGRES_HOST_PORT` | `5432` | PostgreSQL port published on `127.0.0.1` for desktop tools |
| `S3_ALLOWED_ENDPOINTS` | empty | Exact HTTPS S3 origins; empty disables S3 |
| `LEAVE_SCHEMA` | `no` | Retain worker job schema for debugging |
| `LEAVE_JOBDIR` | `no` | Retain worker job directory for debugging |

Both local image names use `QC_TOOL_IMAGE_TAG`; neither image is downloaded
from a legacy release by default. Builds package the current checkout. The source
bind mount supports iterative development, while rebuilding is required after
runtime dependency or Dockerfile changes. The first worker build compiles the
geospatial stack and may take substantially longer than a frontend build.

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

Keep original product recipes and uploaded specification snapshots unchanged.
Raster/vector check behavior remains unchanged on this branch. Infrastructure,
authentication and documentation work must preserve it; use the appropriate
specialist regression suite to verify that contract.

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
