# Local development

This guide describes the Docker Compose workflow provided by
`docker/compose.local.yaml` for changing and testing QC Tool code from a local
checkout. The Compose file uses published application images and overlays the
checkout as source code; it does not build application images.

## Prerequisites

- Docker Engine or Docker Desktop with Docker Compose v2.20 or newer.
- On Apple Silicon, enable support for AMD64 image emulation. The local Compose
  file selects `linux/amd64` by default.

Run all commands from the repository root.

## Configure optional settings

No `.env` file or host boundary path is required to start the stack. Compose
settings can be supplied through the shell or through an optional `.env` file
in the repository root. The file is ignored by Git.

For example, to use another frontend port:

```dotenv
QC_TOOL_PORT=8001
```

Check the resolved configuration before startup:

```bash
docker compose -f docker/compose.local.yaml config --quiet
```

The supported variables and their defaults are listed at the end of this
guide. Compose v2.26 and newer can also print them with
`docker compose -f docker/compose.local.yaml config --variables`.

## Start the development stack

Start in the foreground:

```bash
docker compose -f docker/compose.local.yaml up
```

Or start in the background and wait for every service to become healthy:

```bash
docker compose -f docker/compose.local.yaml up -d --wait
```

The worker starts the complete bundled INSPIRE validator. Its first startup can
take several minutes, especially through AMD64 emulation.

Open <http://127.0.0.1:8000>. If `QC_TOOL_PORT` was changed, use that port
instead. The default development accounts are:

- `admin` / `admin`
- `guest` / `guest`
- `guest2` / `guest2`
- `guest3` / `guest3`

The stack consists of:

- `frontend`: Django development server and frontend user management.
- `worker`: QC scheduler, check processes, embedded PostGIS, and the bundled
  metadata validator.
- `userdb`: PostgreSQL database used by Django.

## Install a boundary package

The current Compose file stores boundaries in the `qc_tool_boundary` named
volume. It does not bind-mount a host boundary directory.

Obtain a compatible package through the
[project boundary guide](https://github.com/eea/copernicus_quality_tools/wiki/Boundaries).
The project's [2.4.6 release notes](https://github.com/eea/copernicus_quality_tools/releases/tag/2.4.6)
also link to the current boundary package. The ZIP archive must contain the
`raster` and `vector` directories directly:

```text
boundary-package.zip
├── raster/
└── vector/
```

After the stack starts, sign in as `admin`, open the `/boundaries/` page on the
frontend (for example, <http://127.0.0.1:8000/boundaries/> when using the
default port), select **Upload Boundary Package**, and upload the ZIP. The
frontend extracts it under
`/mnt/qc_tool_boundary/boundaries`; the frontend and worker share that volume.

## Editing code

The repository is bind-mounted read-only at
`/usr/local/src/copernicus_quality_tools` in the frontend and worker containers.
No image rebuild is needed for ordinary Python, template, static asset, or
product-definition changes.

Django reloads frontend source changes automatically. Each QC job starts a new
Python process, so the next job loads current vector, raster, dispatch, and
check code. Restart the worker after changing its long-running scheduler:

```bash
docker compose -f docker/compose.local.yaml restart worker
```

The frontend runs migrations during startup. Run them explicitly when adding
or changing a migration while the stack is already running:

```bash
docker compose -f docker/compose.local.yaml exec \
  --workdir /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend \
  frontend \
  python3 manage.py migrate
```

The Compose services have no `build` sections, so adding `--build` to `up` does
not rebuild them. Dependency changes and edits to Dockerfiles, entrypoints,
`docker/run_frontend.sh`, or `docker/supervisord.conf` require an explicit image
build and container recreation. Set `QC_TOOL_IMAGE_TAG` to the tag used for
both rebuilt frontend and worker images.

## Debugging status

The default local stack does not start debugpy or publish port 5678. The
checked-in `.vscode/launch.json` is an attach configuration only; it has no
debug server to connect to when `docker/compose.local.yaml` is used by itself.
There is currently no checked-in debug override for the local Compose stack.

Use logs and container shells for the standard workflow. A remote debugger
requires a separately maintained debug image or Compose override before the VS
Code attach configuration can be used.

## Metadata validator

`docker/compose.local.yaml` starts the complete bundled INSPIRE validator with
`RUN_INSPIRE_VALIDATOR=yes` and `USE_LIGHTWEIGHT_VALIDATOR=no`. The worker
health check also requires the bundled validator endpoint to become healthy.

These values are fixed in the current Compose file; shell variables named
`QC_TOOL_RUN_INSPIRE_VALIDATOR` or `QC_TOOL_USE_LIGHTWEIGHT_VALIDATOR` are not
read by it. Switching validator mode requires a Compose override that changes
the worker environment and its health check together.

## Logs, shells, and retained job data

```bash
# Follow application logs.
docker compose -f docker/compose.local.yaml logs -f frontend worker

# Open a Django shell.
docker compose -f docker/compose.local.yaml exec \
  --workdir /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend \
  frontend \
  python3 manage.py shell

# Open a worker shell.
docker compose -f docker/compose.local.yaml exec worker sh

# Open PostgreSQL using the configured database credentials.
docker compose -f docker/compose.local.yaml exec userdb sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Worker jobs write their result, report, log, and output files under
`/mnt/qc_tool_work/work`. Each job's `tmp/` subdirectory and worker PostGIS
schema are deleted by default. Retain them while debugging with:

```bash
LEAVE_JOBDIR=yes LEAVE_SCHEMA=yes \
docker compose -f docker/compose.local.yaml up -d --wait
```

`LEAVE_JOBDIR` retains each job's `tmp/` subdirectory; regular result and output
files already remain in the named work volume. A retained PostGIS schema lives
in the worker container and is lost when that container is recreated.

## Run tests

Start the stack, run the core suite inside the worker where the native
geospatial libraries are installed, and run the Django suite inside the
frontend:

```bash
docker compose -f docker/compose.local.yaml up -d --wait

docker compose -f docker/compose.local.yaml exec \
  -e SKIP_INSPIRE_CHECK=yes \
  worker \
  python3 -m unittest discover \
  -s /usr/local/src/copernicus_quality_tools/src/qc_tool/test \
  -t /usr/local/src/copernicus_quality_tools/src

docker compose -f docker/compose.local.yaml exec \
  --workdir /usr/local/src/copernicus_quality_tools/src/qc_tool/frontend \
  frontend \
  python3 manage.py test dashboard.tests
```

The Django command creates a temporary PostgreSQL test database and applies the
full migration chain. Its tests cover frontend models and views, upload
handling, admin configuration, and persisted reporting metadata.

Run one worker test module with:

```bash
docker compose -f docker/compose.local.yaml exec \
  -e SKIP_INSPIRE_CHECK=yes \
  worker \
  python3 -m unittest qc_tool.test.test_zip_validation
```

## Data and cleanup

The Django database, uploaded boundaries, delivery uploads, frontend state,
shared work files, and submissions use named volumes. A normal shutdown
preserves those volumes:

```bash
docker compose -f docker/compose.local.yaml down
```

The worker's embedded PostGIS database is not mounted as a named volume, so
retained job schemas do not survive worker-container removal. Job result and
output files are in `qc_tool_work` and do survive ordinary container
recreation.

To delete all local QC Tool named volumes and start with empty application
data:

```bash
docker compose -f docker/compose.local.yaml down --volumes
```

This command permanently deletes the local Django database, uploaded boundary
package, delivery uploads, frontend state, work files, and submissions. It does
not delete the bind-mounted source checkout.

## Useful configuration

These are the variables interpolated by `docker/compose.local.yaml`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_PORT` | `8000` | Frontend host port, bound to `127.0.0.1`. |
| `QC_TOOL_PLATFORM` | `linux/amd64` | Platform selected for the published application images. |
| `QC_TOOL_IMAGE_TAG` | `2.4.6` | Tag selected for both published frontend and worker images. |
| `QC_TOOL_POSTGRES_DB` | `qc_tool` | Django PostgreSQL database name. |
| `QC_TOOL_POSTGRES_USER` | `qc_user` | Django PostgreSQL user. |
| `QC_TOOL_POSTGRES_PASSWORD` | `qc_password` | Django PostgreSQL password. |
| `LEAVE_JOBDIR` | `no` | Set to `yes` to retain per-job temporary directories. |
| `LEAVE_SCHEMA` | `no` | Set to `yes` to retain worker PostGIS job schemas. |

Changing PostgreSQL credentials after the `postgres_data` volume has already
been initialized does not update the existing database roles. Use an
intentional volume reset or migrate the database credentials explicitly.
