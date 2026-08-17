# Local development

This guide describes the Docker Compose workflow for changing and debugging QC
Tool Python code from a local checkout.

## Prerequisites

- Docker Engine or Docker Desktop with Docker Compose v2.20 or newer.
- On Apple Silicon, allow Docker Desktop to run AMD64 images using emulation.
  The published QC Tool 2.4.7 images are currently Linux/AMD64 only.

Run all commands from the repository root.

## Configure the development environment

Docker Compose reads development settings from the shell and from a `.env`
file in the repository root. `QC_TOOL_BOUNDARY_PATH` is required; the other
variables have development defaults.

Obtain a compatible package through the
[project boundary guide](https://github.com/eea/copernicus_quality_tools/wiki/Boundaries).
The default image's [2.4.7 release](https://github.com/eea/copernicus_quality_tools/releases/tag/2.4.7)
also provides a Boundary Package download link. Unpack the package, then create
`.env` and set its absolute host path:

```dotenv
QC_TOOL_BOUNDARY_PATH="/absolute/path/to/boundary_package"
```

The package directory must contain the `raster` and `vector` directories
directly:

```text
boundary_package/
├── raster/
└── vector/
```

Paths containing spaces must remain quoted in `.env`. The file is ignored by
Git, so machine-specific paths and local overrides are not committed. You can
also set the variable in the shell for a single command:

```bash
QC_TOOL_BOUNDARY_PATH="/absolute/path/to/boundary_package" \
docker compose -f docker/compose.local.yaml up --build
```

Compose reports an error if `QC_TOOL_BOUNDARY_PATH` is unset. Check the
configuration before startup with:

```bash
docker compose -f docker/compose.local.yaml config --quiet
```

## Start the development stack

```bash
docker compose -f docker/compose.local.yaml up --build
```

To run in the background and wait for healthy services:

```bash
docker compose -f docker/compose.local.yaml up -d --build --wait
```

Open <http://127.0.0.1:8000>. The development accounts are:

- `admin` / `admin`
- `guest` / `guest`

The stack consists of:

- `frontend`: Django development server and frontend user management.
- `worker`: QC scheduler, check processes, embedded PostGIS, and metadata
  validation.
- `userdb`: PostgreSQL database used by Django.

## Editing code

The repository is bind-mounted read-only at
`/usr/local/src/copernicus_quality_tools` in the frontend and worker containers.
No image rebuild is needed for ordinary Python, template, static asset, or
product-definition changes.

Django reloads frontend changes automatically. Each QC job starts a new Python
process, so the next job loads current vector, raster, dispatch, and check code.
Restart the worker after changing its long-running scheduler or scheduler
startup code:

```bash
docker compose -f docker/compose.local.yaml restart worker
```

Run migrations after adding or changing a Django migration:

```bash
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage migrate
```

A source mount cannot install dependencies. Frontend dependency changes require
rebuilding `docker/Dockerfile.frontend.local`. Worker dependency changes require
a matching rebuilt worker image.

## Debug the frontend with VS Code

The debug override enables debugpy and publishes it only on
`127.0.0.1:5678`:

```bash
docker compose \
  -f docker/compose.local.yaml \
  -f docker/compose.local.debug.yaml \
  up --build
```

In VS Code, start the checked-in `Python: Remote Attach` configuration. Debugpy
does not wait for the IDE, so the web application remains usable before a
debugger attaches. Django subprocess debugging and container-to-workspace path
mapping are already configured in `.vscode/launch.json`.

Set `QC_TOOL_DEBUG_PORT` on both the Compose command and the VS Code
configuration if port 5678 is unavailable.

## Metadata validator modes

Local development uses the lightweight metadata validator by default. This
avoids starting Jetty, Squid, and Apache and significantly reduces startup time.

Use the complete bundled INSPIRE validator when its exact behavior is under
test:

```bash
QC_TOOL_RUN_INSPIRE_VALIDATOR=yes \
QC_TOOL_USE_LIGHTWEIGHT_VALIDATOR=no \
docker compose -f docker/compose.local.yaml up --build
```

## Logs and shells

```bash
# Follow application logs.
docker compose -f docker/compose.local.yaml logs -f frontend worker

# Open a Django shell.
docker compose -f docker/compose.local.yaml exec frontend \
  python3 -m qc_tool.frontend.manage shell

# Open a worker shell.
docker compose -f docker/compose.local.yaml exec worker sh
```

Worker jobs write detailed output under `/mnt/qc_tool_work/work` in the worker
container. Temporary job directories and PostGIS schemas are retained by
default for debugging. Restore automatic cleanup when needed:

```bash
LEAVE_JOBDIR=no LEAVE_SCHEMA=no \
docker compose -f docker/compose.local.yaml up --build
```

## Run tests

Start the stack and run the test suite inside the worker, where the required
native geospatial libraries and PostGIS are available:

```bash
docker compose -f docker/compose.local.yaml up -d --build --wait

docker compose -f docker/compose.local.yaml exec \
  -e SKIP_INSPIRE_CHECK=yes \
  worker \
  python3 -m unittest discover \
  -s /usr/local/src/copernicus_quality_tools/src/qc_tool/test \
  -t /usr/local/src/copernicus_quality_tools/src
```

Run one module with:

```bash
docker compose -f docker/compose.local.yaml exec \
  -e SKIP_INSPIRE_CHECK=yes \
  worker \
  python3 -m unittest qc_tool.test.test_vector_check
```

## Data and cleanup

The boundary package is bind-mounted from `QC_TOOL_BOUNDARY_PATH`. The Django
database, uploads, shared work files, and submissions use named volumes. A
normal shutdown preserves all of them:

```bash
docker compose -f docker/compose.local.yaml down
```

Retained worker PostGIS schemas last only until the worker container is
recreated. Job files in the work volume survive recreation.

To delete all local QC Tool named volumes and start with empty application
data:

```bash
docker compose -f docker/compose.local.yaml down --volumes
```

This final command permanently deletes the local database, uploads, work files,
and submissions. It does not delete the bind-mounted boundary package. The
boundary mount is writable, so uploading a package through the frontend
replaces files in the host directory referenced by `QC_TOOL_BOUNDARY_PATH`.

## Useful configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_BOUNDARY_PATH` | None (required) | Absolute host path to an unpacked boundary package containing `raster/` and `vector/`. |
| `QC_TOOL_PORT` | `8000` | Frontend host port. |
| `QC_TOOL_DEBUG_PORT` | `5678` | Debugpy host port when using the debug override. |
| `QC_TOOL_DEBUGPY_VERSION` | `1.8.12` | Debugpy version installed in the local frontend image. |
| `QC_TOOL_PLATFORM` | `linux/amd64` | Container platform for published images. |
| `QC_TOOL_IMAGE_TAG` | `2.4.7` | Published frontend base and worker image tag. |
| `QC_TOOL_POSTGRES_DB` | `qc_tool` | Django PostgreSQL database name. |
| `QC_TOOL_POSTGRES_USER` | `qc_user` | Django PostgreSQL user. |
| `QC_TOOL_POSTGRES_PASSWORD` | `qc_password` | Django PostgreSQL password. |
| `QC_TOOL_RUN_INSPIRE_VALIDATOR` | `no` | Start the complete bundled validator. |
| `QC_TOOL_USE_LIGHTWEIGHT_VALIDATOR` | `yes` | Use lightweight metadata validation. |
| `LEAVE_JOBDIR` | `yes` | Retain temporary job directories. |
| `LEAVE_SCHEMA` | `yes` | Retain temporary worker PostGIS schemas. |

Changing PostgreSQL credentials after the `postgres_data` volume has already
been initialized does not update the existing database roles. Use an intentional
volume reset or migrate the database credentials explicitly.
