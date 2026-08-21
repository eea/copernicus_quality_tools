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

These commands use the default named-volume boundary storage. To use an
existing unpacked package from the host instead, use the override described in
the next section. Do not run a base-only `up` command while using the host
override, because changing the Compose file set switches the boundary mount.

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

## Select boundary storage

Obtain a compatible package through the
[project boundary guide](https://github.com/eea/copernicus_quality_tools/wiki/Boundaries).
The project's [2.4.6 release notes](https://github.com/eea/copernicus_quality_tools/releases/tag/2.4.6)
also link to the current boundary package. Whether zipped or extracted, the
package must contain the `raster` and `vector` directories directly at its
root:

```text
boundary-package.zip
├── raster/
└── vector/
```

### Option 1: Docker named volume

This is the default and requires only `docker/compose.local.yaml`. After the
stack starts, sign in as `admin`, open the `/boundaries/` page on the frontend
(for example, <http://127.0.0.1:8000/boundaries/> when using the default port),
select **Upload Boundary Package**, and upload the ZIP.

The page is expected to be empty before the first upload. The frontend extracts
the package under `/mnt/qc_tool_boundary/boundaries`, which the frontend and
worker share through the `qc_tool_boundary` named volume. Uploading another
package replaces the existing `raster` and `vector` directories in that volume.

### Option 2: Existing host directory

Use `docker/compose.local.boundary-bind.yaml` when an unpacked package already
exists on the host or an external drive. Set its absolute path in `.env`; for
example:

```dotenv
QC_TOOL_BOUNDARY_PATH="/Volumes/SAMSUNG/gisat/QC Tool/boundaries/boundary_package_20260617"
```

The selected directory must contain `raster/` and `vector/` directly. Ensure
that the external drive is connected and available to Docker, then validate and
start with both Compose files:

```bash
docker compose \
  -f docker/compose.local.yaml \
  -f docker/compose.local.boundary-bind.yaml \
  config --quiet

docker compose \
  -f docker/compose.local.yaml \
  -f docker/compose.local.boundary-bind.yaml \
  up -d --wait
```

Keep both `-f` arguments on later `config` or `up` commands while using this
mode. A base-only `up` command intentionally switches back to the named volume.

The override replaces the named-volume mount with the host package and mounts
it read-only. Boundary listing and QC checks can read it, while the application
cannot alter the host files. The **Upload Boundary Package** button remains
visible but cannot write in this mode; switch to named-volume mode for uploads.

### Switch between modes

Finish active jobs before switching because the worker must be recreated and
its embedded PostGIS schemas do not survive recreation. To switch back to the
named volume, omit the override:

```bash
docker compose -f docker/compose.local.yaml \
  up -d --wait --force-recreate frontend worker
```

To switch to the host package, include it:

```bash
docker compose \
  -f docker/compose.local.yaml \
  -f docker/compose.local.boundary-bind.yaml \
  up -d --wait --force-recreate frontend worker
```

Switching does not copy or delete either boundary store. The named-volume
package remains available when switching back. Do not use `down --volumes` to
switch modes; that command deletes other local application data.

## Editing code

The repository is bind-mounted read-only at
`/usr/local/src/copernicus_quality_tools` in the frontend and worker containers.
No image rebuild is needed for ordinary Python, template, static asset, or
other source-code changes.

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

When using the host boundary mode, include
`-f docker/compose.local.boundary-bind.yaml` in this `up` command as well.

`LEAVE_JOBDIR` retains each job's `tmp/` subdirectory; regular result and output
files already remain in the named work volume. A retained PostGIS schema lives
in the worker container and is lost when that container is recreated.

## Run tests

Start the stack in the selected boundary mode as described above. Then run the
core suite inside the worker, where the native geospatial libraries are
installed, and run the Django suite inside the frontend:

```bash
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

The Django database, delivery uploads, frontend state, shared work files, and
submissions use named volumes. Boundaries also use a named volume in the
default mode; host-bind mode reads the external directory instead. A normal
shutdown preserves the named volumes. Use the same Compose file set selected at
startup; the default command is:

```bash
docker compose -f docker/compose.local.yaml down
```

The worker's embedded PostGIS database is not mounted as a named volume, so
retained job schemas do not survive worker-container removal. Job result and
output files are in `qc_tool_work` and do survive ordinary container
recreation.

To delete all local QC Tool named volumes and start with empty application
data, deliberately use the base file so the named boundary volume is included
even if host-bind mode was last used:

```bash
docker compose -f docker/compose.local.yaml down --volumes
```

This command permanently deletes the local Django database, the boundary
package stored in the named volume, delivery uploads, frontend state, work
files, and submissions. It does not delete the bind-mounted source checkout or
a read-only external boundary package.

## Useful configuration

These are the variables interpolated by the base Compose file and the optional
boundary-bind override:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_PORT` | `8000` | Frontend host port, bound to `127.0.0.1`. |
| `QC_TOOL_PLATFORM` | `linux/amd64` | Platform selected for the published application images. |
| `QC_TOOL_IMAGE_TAG` | `2.4.6` | Tag selected for both published frontend and worker images. |
| `QC_TOOL_POSTGRES_DB` | `qc_tool` | Django PostgreSQL database name. |
| `QC_TOOL_POSTGRES_USER` | `qc_user` | Django PostgreSQL user. |
| `QC_TOOL_POSTGRES_PASSWORD` | `qc_password` | Django PostgreSQL password. |
| `QC_TOOL_BOUNDARY_PATH` | Not set | Absolute path to an extracted package; required only by `compose.local.boundary-bind.yaml`. |
| `LEAVE_JOBDIR` | `no` | Set to `yes` to retain per-job temporary directories. |
| `LEAVE_SCHEMA` | `no` | Set to `yes` to retain worker PostGIS job schemas. |

Changing PostgreSQL credentials after the `postgres_data` volume has already
been initialized does not update the existing database roles. Use an
intentional volume reset or migrate the database credentials explicitly.
