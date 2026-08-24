---
title: Getting started
nav_order: 2
has_children: true
---

# Getting started

This is the supported path for running a checkout on a developer workstation.
It uses Docker Compose so the frontend, PostgreSQL database, worker, INSPIRE
validator, and shared storage match the application's runtime assumptions.

## 1. Prerequisites

Install:

- Git;
- Docker Engine or Docker Desktop;
- Docker Compose v2, invoked as `docker compose`.
- network access to the configured container registries and the upstream GitHub
  source archive used by the image builds.

Verify them before cloning:

```bash
git --version
docker version
docker compose version
```

The published worker image currently targets `linux/amd64`. On an ARM computer,
Docker Desktop uses emulation because the local Compose file defaults
`QC_TOOL_PLATFORM` to `linux/amd64`. Worker startup and QC jobs will be slower.

The worker contains PostgreSQL/PostGIS, Java, and the INSPIRE validator. Ensure
Docker has enough memory and disk space for those services and for uploaded
deliveries. The local worker reserves 1 GiB of shared memory and configures a
1,536 MiB Java heap.

## 2. Clone the repository

```bash
git clone https://github.com/eea/copernicus_quality_tools.git
cd copernicus_quality_tools
```

Run all commands in this guide from the repository root.

## 3. Validate the Compose configuration

```bash
docker compose -f docker/compose.local.yaml config --quiet
```

No output means the configuration is valid.

## 4. Start QC Tool

```bash
docker compose -f docker/compose.local.yaml up --build --detach
```

On the first run, this command:

1. builds the frontend runtime from the checked-in Dockerfile and pinned
   requirements;
2. pulls the published worker and PostgreSQL images if necessary;
3. creates persistent Docker volumes;
4. waits for PostgreSQL;
5. applies Django migrations and collects static files;
6. creates development-only demo users;
7. starts the frontend and worker health checks.

The repository is mounted read-only over the source packaged in both
containers. Frontend Python changes are picked up by Django's development
server. Restart the worker after changing worker or shared Python code.

## 5. Watch startup

```bash
docker compose -f docker/compose.local.yaml ps
docker compose -f docker/compose.local.yaml logs --follow frontend worker
```

Wait until `userdb`, `frontend`, and `worker` are healthy. Press `Ctrl+C` to
stop following logs; the detached services continue running.

If the full INSPIRE validator is enabled, the worker can take several minutes
to become healthy, particularly under CPU emulation.

## 6. Sign in

Open <http://localhost:8000/accounts/login/>.

The local configuration sets both `QC_TOOL_ENVIRONMENT=development` and
`QC_TOOL_BOOTSTRAP_DEMO_USERS=yes`, so these local-only accounts are created:

| Username | Password | Purpose |
| --- | --- | --- |
| `admin` | `admin` | Django superuser and QC Tool administrator |
| `guest` | `guest` | Ordinary local user |
| `guest2` | `guest2` | Additional test user |
| `guest3` | `guest3` | Additional test user |

Never copy these flags or credentials into a shared or production environment.
The startup script refuses to create them outside development and test.

## 7. Confirm the installation

```bash
curl --fail http://localhost:8000/accounts/login/
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage check
```

In the browser, confirm that you can:

1. sign in and sign out;
2. open the Deliveries page;
3. open Django Admin as the local `admin` user;
4. see both PostgreSQL and the worker as healthy in `docker compose ps`.

This validates the application stack, not a complete QC run. The repository
does not ship a ready-to-upload boundary package, and every job pins a boundary
generation before executing checks. An operator must provide and activate a ZIP
with top-level `raster/` and `vector/` directories before the first job. See
[Boundary packages](../user-guide/administration.md#boundary-packages).

## 8. Make a source change

The local frontend uses Django's development server and the checkout bind
mount. Most Python and template edits reload automatically. Browser JavaScript
and CSS may require a hard refresh.

After changing worker or shared code:

```bash
docker compose -f docker/compose.local.yaml restart worker
```

The frontend image build downloads `QC_TOOL_SOURCE_VERSION` from the upstream
GitHub repository before the checkout is mounted over it. The default is
`master`. If you override it, use a branch/tag/commit that already exists in
`eea/copernicus_quality_tools`; an unpushed local or fork-only ref cannot be
downloaded and the image build will fail.

Rebuild when changing Dockerfiles or pinned dependencies:

```bash
docker compose -f docker/compose.local.yaml build --no-cache frontend
docker compose -f docker/compose.local.yaml up --detach
```

## 9. Stop QC Tool

```bash
docker compose -f docker/compose.local.yaml down
```

This stops containers but keeps the named volumes and database.

> **Destructive reset:** `docker compose -f docker/compose.local.yaml down --volumes`
> deletes the local PostgreSQL database, users, deliveries, job state, and all
> named-volume data. Use it only when you intentionally want a clean install.

## Next steps

- [Local development workflow](local-development.md)
- [Run the test suites](../development/testing.md)
- [Understand the repository](../architecture/repository-layout.md)
- [Create and administer users](../user-guide/administration.md)
- [Troubleshoot startup](troubleshooting.md)
- [Prepare a production deployment](../deployment/index.md)
