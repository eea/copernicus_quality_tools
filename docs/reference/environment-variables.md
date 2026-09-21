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
| `FRONTEND_DB_PATH` | `/var/lib/qc_tool/frontend.sqlite3` | frontend | SQLite database path when `DB_ENGINE` is not `postgres` |
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

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_ENGINE` | `sqlite` | Set `postgres` for PostgreSQL |
| `POSTGRES_HOST` | `qc_tool_userdb` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `qc_tool_frontend` | Database name |
| `POSTGRES_USER` | `qc_tool_user` | Database user |
| `POSTGRES_PASSWORD` | development fallback | Required for PostgreSQL in secure mode |
| `QC_TOOL_POSTGRES_HOST_PORT` | `5432` in local Compose | Host port published on `127.0.0.1`; does not change the container database port |

The EEA Compose profile maps its `QC_TOOL_POSTGRES_PASSWORD` substitution into
`POSTGRES_PASSWORD` for both database and frontend.

## Frontend behavior

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_URL` | application default | Public API base shown by UI/docs |
| `SHOW_LOGO` | `yes` | Show Copernicus branding |
| `UPDATE_JOB_STATUSES` | `yes` | Browser delivery-page polling |
| `UPDATE_JOB_STATUSES_INTERVAL` | `30000` ms | Browser polling interval |
| `REFRESH_JOB_STATUSES_BACKGROUND` | `yes` | Start WSGI background refresh loop |
| `REFRESH_JOB_STATUSES_BACKGROUND_INTERVAL` | `60` s | Background refresh interval |
| `WORKER_ALIVE_TIMEOUT` | `5` s | Worker status request timeout |
| `MAINTENANCE_MODE` | `no` | Return maintenance responses outside Admin |
| `CASE_INSENSITIVE_USERNAMES` | `no` | Enable the case-insensitive login backend |
| `RESUMABLE_SIMULTANEOUS_UPLOADS` | `4` | Browser parallel upload chunks; allowed 1–32 |
| `QC_TOOL_WEB_WORKERS` | `1` | Gunicorn worker processes; keep one currently |
| `QC_TOOL_WEB_TIMEOUT_SECONDS` | `120` | Gunicorn request timeout |

## Development-only startup

| Variable | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_BOOTSTRAP_DEMO_USERS` | `no` | Create predictable demo accounts; refused outside dev/test |
| `QC_TOOL_DEV_SERVER` | `no` | Run Django `runserver` instead of Gunicorn |
| `QC_TOOL_MIGRATE_ON_STARTUP` | `no`; local Compose sets `yes` | Initialize draft models or apply released migrations before startup; dev/test only. Existing draft columns are not altered. Otherwise startup runs `database check` |

Never enable these settings in production. Production schema changes run as a
serialized deployment job using the pinned release image. See
[Database migrations](../development/database-migrations.md).

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
| `JAVA_MAX_MEM` | image default `1536` MiB | Validator Java heap budget |
| `LEAVE_SCHEMA` | `no` | Retain job schema for debugging |
| `LEAVE_JOBDIR` | `no` | Retain job directory for debugging |
| `SKIP_INSPIRE_CHECK` | `no` | Test-only external INSPIRE bypass |

Worker API calls use the shared token stored under `WORK_DIR`; there is no
operator-configured plaintext token environment variable.

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
