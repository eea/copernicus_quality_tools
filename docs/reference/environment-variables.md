---
title: Environment variables
parent: Reference
nav_order: 1
---

# Environment variables

Paths are interpreted inside each container. Frontend and workers must see the
same shared data through compatible container paths.

## Paths and shared data

| Variable | Default | Services | Purpose |
| --- | --- | --- | --- |
| `PRODUCT_DIRS` | packaged `product_definitions` | frontend, worker | Colon-separated recipe directories for explicitly imported products; does not populate the catalog |
| `BOUNDARY_DIR` | `/mnt/qc_tool_boundary/boundaries` | frontend, worker | Immutable boundary generations |
| `INCOMING_DIR` | test-data fallback | frontend, worker | Uploaded/materialized deliveries |
| `WORK_DIR` | `/mnt/qc_tool_volume/work` | frontend, worker | Results, logs, job files, worker token |
| `SUBMISSION_DIR` | empty/disabled | frontend | Successful submission copies |
| `FRONTEND_DB_PATH` | `/var/lib/qc_tool/frontend.sqlite3` | frontend | SQLite database path when `DB_ENGINE=sqlite` |
| `DJANGO_STATIC_ROOT` | `/var/lib/qc_tool/static` in secure environments | frontend | Collected WhiteNoise static files |

`WORK_DIR`, `BOUNDARY_DIR`, and `INCOMING_DIR` are shared contracts. Do not map
the same setting to unrelated storage in frontend and worker.

## Django environment and HTTP security

| Variable | Default | Notes |
| --- | --- | --- |
| `QC_TOOL_ENVIRONMENT` | `development` in source; `production` in image | Values other than `development`/`test` enable fail-closed secure mode |
| `DJANGO_DEBUG` | enabled only in development/test | Secure mode rejects `yes` |
| `DJANGO_SECRET_KEY` | development-only fallback | Required in secure mode; use a long random secret |
| `DJANGO_ALLOWED_HOSTS` | local hosts | Secure mode requires explicit non-wildcard hosts, comma-separated |
| `CSRF_TRUSTED_ORIGINS` | empty | Comma-separated full trusted origins, including scheme |
| `DJANGO_SESSION_COOKIE_SECURE` | secure-mode value | Override only for a reviewed topology |
| `DJANGO_CSRF_COOKIE_SECURE` | secure-mode value | Override only for a reviewed topology |
| `DJANGO_SECURE_SSL_REDIRECT` | `no` | Enable in Django only when it can identify secure requests correctly |
| `DJANGO_TRUST_PROXY_SSL_HEADER` | `no` | Trust `X-Forwarded-Proto` only from a sanitizing proxy |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | HSTS lifetime, up to ten years |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | `no` | Enable only when all subdomains are HTTPS |
| `DJANGO_SECURE_HSTS_PRELOAD` | `no` | Requires a deliberate preload decision |

Boolean values accept `1/0`, `true/false`, `yes/no`, or `on/off`.

## Frontend database

Production Compose also requires `QC_TOOL_FRONTEND_IMAGE` and
`QC_TOOL_WORKER_IMAGE`: matching reviewed registry image digests, without legacy
defaults. Both Dockerfiles package the checkout from the repository-root build
context. `VERSION` identifies the release and `SOURCE_REVISION` records commit
provenance; neither selects a second GitHub source download.
`QC_TOOL_PORT` selects the Compose frontend's loopback host port (default `8000`);
use a distinct value when rehearsing a separate target beside a retained source.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_ENGINE` | `sqlite` | Only `sqlite` and `postgres` are accepted; unknown values fail startup |
| `POSTGRES_HOST` | `qc_tool_userdb` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `qc_tool_frontend` | Initially configured primary database. An explicitly reviewed Admin switch can select another database on this cluster through the persistent private selection pointer. |
| `POSTGRES_USER` | `qc_tool_user` | Database user |
| `POSTGRES_PASSWORD` | development fallback | Required for PostgreSQL in secure mode |
| `QC_TOOL_RESTORE_DATABASE` | unset | Optional operator fallback: exact name of a separately provisioned entirely empty database on the configured cluster. Normally Admin creates a unique destination per operation using the configured identity's database-creation privilege. The fallback must differ from the active database. Existing databases are never dropped/reset; switching is a separate reviewed Admin action. |
| `QC_TOOL_POSTGRES_HOST_PORT` | `5432` in local Compose | Host port published on `127.0.0.1`; does not change the container database port |

The EEA Compose profile maps its `QC_TOOL_POSTGRES_PASSWORD` substitution into
`POSTGRES_PASSWORD` for both database and frontend.

Frontend image build arguments `POSTGRES_CLIENT_MAJOR` (default `14`) and
`POSTGRES_CLIENT_VERSION` (default `14.24-1.pgdg13+2`) select the reviewed PGDG
client package for both AMD64 and ARM64. These are build arguments, not runtime
environment switches. Update both together after reviewing compatibility;
native operations require the client/server major to match. Both frontend
Dockerfiles verify the official PGDG signing key checksum and use APT signature
validation over HTTPS. `psycopg2-binary` alone does not supply `pg_dump` or
`pg_restore`.

## Frontend behavior

### Boundary package limits

Boundary uploads use one deployment policy for archive copying, ZIP validation
and extraction. Defaults accommodate large geospatial boundary packages; lower
them when the deployment's expected data permits. Integer values must be
positive; the compression ratio must be finite and at least 1. Invalid values
refuse application settings loading rather than disabling a check.

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_BOUNDARY_MAX_ARCHIVE_BYTES` | `4294967296` (4 GiB) | Maximum compressed boundary ZIP size |
| `QC_TOOL_BOUNDARY_MAX_MEMBER_BYTES` | `4294967296` (4 GiB) | Maximum expanded size of one member |
| `QC_TOOL_BOUNDARY_MAX_UNCOMPRESSED_BYTES` | `34359738368` (32 GiB) | Maximum sum of expanded member sizes |
| `QC_TOOL_BOUNDARY_MAX_MEMBERS` | `10000` | Maximum ZIP entry count, including directories |
| `QC_TOOL_BOUNDARY_MAX_COMPRESSION_RATIO` | `100` | Maximum expanded/compressed ratio, per file and for the package |
| `QC_TOOL_BOUNDARY_MAX_PATH_LENGTH` | `1024` | Maximum UTF-8 member path size in bytes |
| `QC_TOOL_BOUNDARY_MAX_PATH_COMPONENT_BYTES` | `255` | Maximum UTF-8 size of one path component |
| `QC_TOOL_BOUNDARY_MAX_PATH_DEPTH` | `32` | Maximum member path depth |

These settings affect boundary packages only; delivery archives and
administrative transfer packages have separate policies. Increasing one bound
does not disable the others or allow unsafe archive paths. Custom Django
settings can provide the same typed values in `QC_TOOL_BOUNDARY_PACKAGE_LIMITS`,
using `BoundaryPackageLimits` field names; invalid or unknown keys are refused.

Provision boundary staging for the compressed ZIP plus extracted content and
retain room for the currently active generations and any legacy snapshot.
The inspected approximately 2.4 GiB boundary ZIP requires roughly 27 GiB (29 GB)
for its Django upload spool, staged archive and extracted content together,
before retained generations or a legacy snapshot. Larger permitted packages can
need more. Proxy buffering may hold additional copies on its own filesystem;
`QC_TOOL_UPLOAD_TEMP_DIR` controls Django's upload spool location.
Configure proxy body limits and request timeouts for the entire upload and
activation duration, and monitor disk capacity. Raising the safety limits does
not change those infrastructure limits.

### Administrative data transfer

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_TRANSFER_DIR` | `WORK_DIR/data-transfer` | Private 0700 persistent staging, journals, packages and `database-selection.json`, shared by every frontend; never expose as media. Preserve it across restarts and deployments. |
| `QC_TOOL_TRANSFER_MAX_RECORDS` | `250000` | Combined source accounts/business rows in a portable package, configurable from 1 to 1,000,000; native PostgreSQL backups have no portable row cap |
| `QC_TOOL_TRANSFER_MAX_ARCHIVE_BYTES` | `17179869184` (16 GiB) | Maximum uploaded/generated package size |
| `QC_TOOL_TRANSFER_MAX_EXPANDED_BYTES` | `68719476736` (64 GiB) | Maximum total artifact inventory size |
| `QC_TOOL_TRANSFER_MIN_FREE_BYTES` | `536870912` (512 MiB) | Free-space reserve during upload and before archive/restore writes |
| `QC_TOOL_POSTGRES_TOOL_TIMEOUT` | `3600` seconds | Native PostgreSQL tool timeout per invocation; integer from 1 to 86400. Timeouts retain maintenance and require recovery; they do not reset a destination. |
| `QC_TOOL_UPLOAD_TEMP_DIR` | OS temporary directory | Optional preprovisioned private directory for Django multipart upload spooling, sized for the configured maximum uploads |

Fixed reader bounds also cap individual members at 16 GiB, record JSON at
128 MiB, metadata at 16 MiB, ZIP members at 100,000, the central directory at
64 MiB and decompression ratio at 1000. Raising one environment limit does not
disable these checks. Configure proxy upload limits/timeouts and disk monitoring
for the intended package sizes. Define private-package retention; active or
recoverable operations must not be removed. See
[record transfers](../user-guide/record-transfers.md).

Portable exports count the complete selected graph before loading record
contents. The review shows the count and configured limit. Creation and the
runner check it again; nothing is truncated or split. Product units count as
records, even when they have no delivery or job. Portable records and their
review plans are processed in memory: size frontend capacity for the largest
intended package before raising this limit. The 128 MiB record-document limit
still applies, independently of row count. A full native backup uses PostgreSQL
tools to stream the database and preserves all SQL rows; restoring it uses a
separate database rather than appending to the active one.

The default native PostgreSQL profile preserves all database rows, including
credential hashes and sessions; portable profiles intentionally filter them.
Native archives are not encrypted by the application. Keep private staging at
`0700`/`0600`, require HTTPS and administrator authorization for downloads, and
use encrypted external backup storage. `DJANGO_SECRET_KEY`, S3 credentials,
PostgreSQL cluster roles and matching application files need separate backups.

For large packages, set `QC_TOOL_UPLOAD_TEMP_DIR` to a real private directory
owned by the frontend runtime UID and backed by sufficient durable/temporary
capacity; provision it before starting Django. All multipart uploads use this
setting, including normal delivery uploads. Proxy buffering, Django spooling and
transfer staging can coexist. The transfer reserve does not protect a default
container `/tmp` filesystem while the body is still being uploaded. An unset
value preserves the OS default; do not point it at a public media directory.

### Other frontend settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_URL` | application default | Public API base shown by UI/docs |
| `SHOW_LOGO` | `yes` | Show Copernicus branding |
| `UPDATE_JOB_STATUSES` | `yes` | Browser delivery-page polling |
| `UPDATE_JOB_STATUSES_INTERVAL` | `30000` ms | Browser polling interval |
| `REFRESH_JOB_STATUSES_BACKGROUND` | `yes` | Start WSGI background refresh loop |
| `REFRESH_JOB_STATUSES_BACKGROUND_INTERVAL` | `60` s | Background refresh interval |
| `WORKER_ALIVE_TIMEOUT` | `5` s | Worker status request timeout |
| `CASE_INSENSITIVE_USERNAMES` | `no` | Enable the case-insensitive login backend |
| `RESUMABLE_SIMULTANEOUS_UPLOADS` | `4` | Browser parallel upload chunks; allowed 1–32 |
| `QC_TOOL_WEB_WORKERS` | `1` | Gunicorn processes; startup rejects other values until status refresh runs outside WSGI |
| `QC_TOOL_WEB_TIMEOUT_SECONDS` | `120` | Gunicorn worker heartbeat timeout; the single `gthread` process has four request threads. This does not limit an individual upload's duration. |

Maintenance uses persistent application state controlled through **Admin →
Maintenance mode** or the `maintenance` command. It requires no Docker
environment switch. The runtime still recognizes `MAINTENANCE_MODE=yes` from
older custom deployments as a compatibility override that the UI cannot turn
off; current manifests omit it. See the [maintenance runbook](../deployment/maintenance.md).

## Development-only startup

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_BOOTSTRAP_DEMO_USERS` | `no` | Create predictable demo accounts; refused outside dev/test |
| `QC_TOOL_DEV_SERVER` | `no` | Run Django `runserver` instead of Gunicorn |
| `QC_TOOL_INITIALIZE_ON_STARTUP` | `no`; local Compose sets `yes` | Initialize an entirely empty database before startup; dev/test only. A complete matching database is unchanged; partial or foreign schemas and detected model drift are refused. Otherwise startup runs read-only `database check` |

Never enable these settings in production. Initialize an entirely empty
production target through an explicit deployment job using the pinned release
image. Restore a prepared current-schema copy separately; initialization does
not upgrade existing tables. See
[Database initialization](../development/database-migrations.md).

## Worker connectivity and debugging

| Variable | Default | Purpose |
| --- | --- | --- |
| `PULL_JOB_URL` | `http://qc_tool_frontend:8000/pull_job` | Private frontend queue endpoint |
| `WORKER_ADDR` | `0.0.0.0` | Worker HTTP bind address |
| `WORKER_PORT` | `8000` | Worker HTTP port |
| `PG_HOST` | `127.0.0.1` | Worker scratch PostGIS host |
| `PG_PORT` | `5432` | Worker scratch PostGIS port |
| `PG_USER` | `qc_job` | Worker scratch role |
| `PG_DATABASE` | `qc_tool_db` | Worker scratch database |
| `INSPIRE_SERVICE_URL` | bundled validator default | Validator endpoint seen from worker |
| `USE_LIGHTWEIGHT_VALIDATOR` | `no` | Use lightweight metadata validator |
| `RUN_INSPIRE_VALIDATOR` | image entrypoint default | Start bundled validator service |
| `RUN_POSTGRES` | image entrypoint default | Start embedded PostgreSQL/PostGIS |
| `JAVA_MAX_MEM` | image default `1536` MiB | Bundled validator maximum Java heap; numeric values require at least `1024` MiB. Entrypoint passes this budget directly to the supervised JVM. |
| `HTTP_PROXY_HOST`, `HTTP_PROXY_PORT` | `localhost`, `3128` | Bundled validator HTTP proxy; host `none` disables it. |
| `HTTPS_PROXY_HOST`, `HTTPS_PROXY_PORT` | `none`, `3129` | Bundled validator HTTPS proxy; host `none` disables it. |
| `HTTP_PROXY_USERNAME`, `HTTP_PROXY_PASSWORD`, `HTTPS_PROXY_USERNAME`, `HTTPS_PROXY_PASSWORD` | unset | Optional proxy credentials, preserved as individual JVM arguments and omitted from startup logs. |
| `LEAVE_SCHEMA` | `no` | Retain job schema for debugging |
| `LEAVE_JOBDIR` | `no` | Retain job directory for debugging |
| `SKIP_INSPIRE_CHECK` | `no` | Test-only external INSPIRE bypass |

Worker API calls use the shared token stored under `WORK_DIR`; there is no
operator-configured plaintext token environment variable.

The entrypoint derives `JAVA_OPTIONS` from the memory and proxy settings and
Supervisor passes it to Java. Set the documented settings rather than overriding
`JAVA_OPTIONS`. The `max`/`0`/empty memory setting uses host memory reported by
`/proc/meminfo`; use an explicit numeric budget below the container's memory
limit for a predictable production allocation.

## S3 policy

| Variable | Frontend default | Worker default | Constraint |
| --- | ---: | ---: | --- |
| `S3_ALLOWED_ENDPOINTS` | empty | empty | Comma-separated exact HTTPS origins; empty disables S3 |
| `S3_CREDENTIALS_DIR` | `WORK_DIR/s3_credentials` | n/a | Persistent private credential directory, owned by the frontend runtime UID; directory `0700`, files `0600` |
| `S3_CONNECT_TIMEOUT_SECONDS` | `3` | `3` | Positive finite seconds |
| `S3_READ_TIMEOUT_SECONDS` | `10` | `30` | Positive finite seconds |
| `S3_MAX_LISTED_OBJECTS` | `1000` | `1000` | 1–1000 |
| `S3_MAX_DOWNLOAD_BYTES` | n/a | 50 GiB | Positive total streamed bytes |

The allowlist must be identical in frontend and worker. Entries cannot contain
whitespace padding, credentials, paths, query strings, fragments, unsafe IP
literals, or HTTP origins.

The database stores an opaque `credential_ref`, not S3 access or secret keys.
New API registrations save credentials in `S3_CREDENTIALS_DIR`; authenticated
workers receive only the credentials for their claimed job. Keep the directory
outside static files, incoming deliveries, job folders and publication folders.
If overriding the default, mount persistent storage at that container path and
include it in restricted, encrypted backups. A SQL-only legacy import leaves
credential references empty; re-register those sources with current credentials
before starting new QC work. See [credential operations](../deployment/operations.md#s3-credentials).

## Delivery archive limits

Worker ZIP extraction reads these optional variables. Defaults are deliberately
large for geospatial deliveries; reduce them where product expectations permit.

| Variable | Default |
| --- | ---: |
| `DELIVERY_ARCHIVE_MAX_ARCHIVE_BYTES` | 50 GiB |
| `DELIVERY_ARCHIVE_MAX_MEMBERS` | 25,000 |
| `DELIVERY_ARCHIVE_MAX_MEMBER_BYTES` | 50 GiB |
| `DELIVERY_ARCHIVE_MAX_UNCOMPRESSED_BYTES` | 100 GiB |
| `DELIVERY_ARCHIVE_MAX_COMPRESSION_RATIO` | 100 |
| `DELIVERY_ARCHIVE_MAX_PATH_BYTES` | 1,024 |
| `DELIVERY_ARCHIVE_MAX_COMPONENT_BYTES` | 255 |
| `DELIVERY_ARCHIVE_MAX_PATH_DEPTH` | 32 |

Invalid, zero, negative, non-finite, or out-of-range values fail closed.
