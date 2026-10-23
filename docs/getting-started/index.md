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

The local stack builds both images for the Docker host architecture by default.
For an explicit target, set `DOCKER_DEFAULT_PLATFORM`, or include
`docker/compose.platform.yaml` with `QC_TOOL_PLATFORM`. Emulating another CPU
architecture can make worker startup, compilation and QC jobs substantially slower.

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
5. initializes an entirely empty database from current models, then collects
   static files;
6. creates development-only demo users;
7. starts the frontend and worker health checks.

The repository is mounted read-only over the source packaged in both
containers. Frontend Python changes are picked up by Django's development
server. Restart the worker after changing worker or shared Python code.

v3.0.0 builds its schema directly from models and ships no migration or legacy
conversion machinery. Initialization does not import products or upgrade existing
tables. A complete matching database is unchanged; partial or foreign schemas
and detected model drift are refused. Model changes require a separate fresh development target;
restarting never resets retained users or records. See
[Database initialization](../development/database-migrations.md).

Normal production startup validates schema read-only. Local Compose enables
`QC_TOOL_INITIALIZE_ON_STARTUP=yes` for development. Production initialization is
an explicit operator command against an entirely empty database; a prepared
current-schema copy is restored separately.

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
| `product_manager` | `product_manager` | Product manager awaiting product assignments |

On an empty local database, bootstrap creates exactly these three usernames.
Reruns are non-destructive: they do not reset existing passwords, replace
roles or grants, or delete accounts left by an earlier local configuration.

The product catalog starts empty. Sign in as `admin`, open **Products → Upload
specification**, and add the reviewed product JSON files you want to use. Bundled
files in `product_definitions/` are examples to choose from; startup does not
import them. Assign the resulting products to `guest` or `product_manager` in
**Django Admin → Users → Product grants** before those accounts begin product work.

The product manager keeps the ordinary `default` permissions and gains
cross-user delivery and job visibility only for its assigned products. It can
review those products' submissions and resolve their submission conflicts through
the scoped Admin pages. It cannot mutate another user's delivery outside that
workflow, is not a QC Tool administrator, and cannot see other products.

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
2. land on Dashboard and open Deliveries, Products, and API Access
   from the workspace sidebar;
3. open Django Admin as the local `admin` user;
4. see both PostgreSQL and the worker as healthy in `docker compose ps`.

Before adding specifications, **Products** should show an empty catalog. After
an administrator uploads a JSON specification, only the added product should
appear. Restarting the stack preserves the catalog without adding bundled products.

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

Both images build from the current checkout. `QC_TOOL_SOURCE_VERSION` is an
optional provenance label; unpushed local changes are included without fetching
an upstream branch. The worker build uses the supported Python 3.12 and geospatial
runtime rather than overlaying current source onto a legacy Python 3.8 image.
The first full worker build compiles GDAL and Squid and can take substantial time.

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
