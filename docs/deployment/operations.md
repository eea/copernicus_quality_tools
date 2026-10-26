---
title: Operations
parent: Deployment
nav_order: 2
---

# Operations

For file browsing, folder ZIP downloads, additional mounted locations and optional
desktop SFTP access, see [Storage browser and desktop connections](storage-access.md).
For the Azure VM mount layout, startup identity guard, filesystem probe and
deliberate move from existing volumes, see [EEA persistent storage](eea-storage.md).

## Deployment command setup

Use the same Compose project name, env file, and Compose-file set for every
command. For the examples below, define a shell function for the selected
profile:

```bash
QC_RELEASE_PROJECT=qc_tool_app
QC_RELEASE_ENV_FILE=/secure/path/qc-tool.env
QC_RELEASE_COMPOSE_FILE=docker/docker-compose.eea.yml

qc_compose() {
  docker compose \
    --project-name "$QC_RELEASE_PROJECT" \
    --env-file "$QC_RELEASE_ENV_FILE" \
    -f "$QC_RELEASE_COMPOSE_FILE" \
    "$@"
}
```

Adapt this once for the deployment; do not commit the secret env file.
When using `compose.eea-storage.yaml`, add it as a second `-f` argument in this
function and use that same file set for every operation. Its mount replacement
requires Compose 2.24.4 or later. Adding the override to a running installation
does not move its existing files or database.

## Health and logs

```bash
qc_compose ps
qc_compose logs --tail 200 frontend worker userdb
qc_compose logs --follow frontend worker
```

Monitor:

- frontend `/health` liveness and error rate (login is intentionally read-only
  during maintenance);
- database connectivity and storage;
- worker and validator health;
- waiting/running job age;
- incoming, work, boundary, and static storage capacity;
- repeated authentication/authorization failures;
- S3 upstream failures by stable error code.

For unavailable upload storage, check the
[incoming-directory layout, mount permissions and temporary storage](../getting-started/troubleshooting.md#delivery-uploads-report-unavailable-storage)
before changing volume types.

For the EEA persistent-storage profile, also monitor the real host mount and
the configured storage identity. The container guard refuses missing or wrong
storage at startup; host mount dependencies and monitoring must prevent and
detect later mount failures. Do not repair an outage by creating empty local
folders or replacing the identity marker. Run `python3 -m qc_tool.storage check`
and the explicit `probe` against the mounted target after provisioning or
changing its filesystem. A probe does not prove Azure crash recovery or replace
a backup/restore exercise.

Docker health status is an observation, not an automatic recovery mechanism.
Alert on unhealthy services and replace the complete worker container after a
scheduler failure. Never restart only its scheduler inside a surviving worker:
older validator process groups may still own database/file writes.

Use the supplied `init: true` container setting, or an equivalent child-reaping
init in another orchestrator. Administrative transfer runners are separate
processes in the frontend container; they inherit its runtime UID, limits and
persistent `WORK_DIR`, and keep maintenance pinned after a crash. Check the
owning transfer before restarting/replacing a frontend and use its recovery
workflow afterwards. Restarting never grants permission to clear its pin.

### Transfer capacity and ingress

The frontend uses one Gunicorn process with four request threads, so a long
upload can run while other users browse. Keep one process while WSGI owns the
background job refresher. `QC_TOOL_WEB_TIMEOUT_SECONDS` monitors the threaded
worker's heartbeat; it is not an upload deadline. Configure proxy body/read
timeouts and storage capacity separately. A boundary upload's browser waits up
to 30 minutes for transfer and validation together; a lost response does not
prove activation failed, so check Boundaries before retrying.

Set ingress request size, upload/read timeout and temporary-file capacity for the
chosen transfer limits. A proxy's default 1 MiB body limit cannot carry the
default 16 GiB package limit. Do not disable limits globally: apply an explicit
operator-approved limit to the Admin transfer upload route and retain request
timeouts/rate controls. Review ingress buffering as well as Django's temporary
upload directory; large multipart bodies can occupy both before transfer staging
begins. Mount and monitor sufficient private temporary storage for the frontend.

Budget space for an uploaded package, validated/extracted artifacts, the final
published files, SQL growth and rollback/recovery journals together. The default
expanded artifact limit is 64 GiB and the 512 MiB reserve is an emergency floor,
not a capacity plan. Check source/target volume drivers for POSIX locking, atomic
rename and durable file/directory synchronization. Set resource limits only after
measuring representative exports/imports; image health and synthetic CI tests do
not establish production throughput or maximum package capacity.

The supplied Compose files pass these frontend settings through. Values are
bytes unless stated otherwise:

| Setting | Default | Purpose |
| --- | --- | --- |
| `QC_TOOL_TRANSFER_DIR` | `WORK_DIR/data-transfer` | Private persistent package and journal storage |
| `QC_TOOL_TRANSFER_MAX_RECORDS` | 250,000 | Portable record graph limit |
| `QC_TOOL_TRANSFER_MAX_ARCHIVE_BYTES` | 17,179,869,184 (16 GiB) | Complete ZIP limit |
| `QC_TOOL_TRANSFER_MAX_MEMBER_BYTES` | Configured archive limit | One included file, including the native dump |
| `QC_TOOL_TRANSFER_MAX_EXPANDED_BYTES` | 68,719,476,736 (64 GiB) | Total expanded package contents |
| `QC_TOOL_TRANSFER_MIN_FREE_BYTES` | 536,870,912 (512 MiB) | Free-space reserve |
| `QC_TOOL_UPLOAD_TEMP_DIR` | System temporary directory | Browser multipart spool storage |
| `QC_TOOL_POSTGRES_TOOL_TIMEOUT` | 3,600 seconds | Native tool deadline |

Defaults keep transfer journals on the existing mounted work volume. A custom
transfer or upload-temporary path must be a private container path backed by a
sized mounted volume; a host pathname in an environment file does not create a
mount. Preserve transfer storage across frontend replacements. Recreate the
frontend after changing its environment, then inspect the rendered Compose
configuration and repeat the capacity review. Coordinate archive, member,
expanded, ingress and physical-storage limits; increasing one alone is insufficient.

For a large existing package, bypass browser/proxy buffering by copying it onto
private mounted operator storage and staging it in the frontend container:

```bash
qc_compose exec -T frontend python3 -m qc_tool.frontend.manage \
  data_transfer stage-file /private/backups/package.zip --actor administrator --records-only
```

Use the actual active administrator's username and a container-visible source
path. The result identifies a staged operation for Admin review; it does not
apply records, initialize a schema or switch databases. Omit `--records-only`
only to include the package's available files. Server staging still validates
the complete package and checks storage limits.

Never log Authorization headers, S3 secrets, raw delivery contents, session
records, or one-time API credentials.

## Maintenance mode

Administrators use **Admin → Maintenance mode** to block application writes,
interrupt QC jobs and check application quiescence. Wait for **ready** before
backing up database and storage together. Unreachable workers and ongoing
pre-existing writer requests keep the state **stopping**. Signed-in users and API
clients can continue authorized read-only browsing, downloads and audited read
POSTs. The application shows a maintenance notice and disables write controls;
the server rejects mutations, including ordinary Admin edits and login/logout.
Read-only sessions, suppressed result refresh and token-use updates, and a
database-write guard protect the ready state. New reads do not block readiness.
The page displays the last confirmed readiness time. Recheck immediately before
backup if services restarted or time has elapsed. Operator `on`/`check` commands
return nonzero until readiness is confirmed, so scripts must honor that status.

Follow the [maintenance runbook](maintenance.md) for the full procedure, recovery
commands and deployment requirements. The UI and `maintenance` command use the
same persistent state; no Docker environment switch or container restart is
needed to turn normal maintenance on or off. Maintenance does not grant SQL
exclusivity or execute schema changes.
Stop services and close all readers before DDL or database replacement, even if
the application already reports ready.

## Backups

Back up the frontend database and required shared volumes as one coherent
system. The database references files under incoming, work and publication storage.

**Admin → Maintenance → Back up & restore → Create a backup** always preserves the complete PostgreSQL
schema, data, credential hashes and database metadata. Its optional sections all
start selected: specifications, boundaries, delivery ZIPs, QC artifacts,
publications, PostgreSQL globals and supported deployment configuration with
private S3 credentials, the available worker token, referenced PostgreSQL TLS
files and inert specification/boundary activation metadata.
Review the selected/omitted/unavailable statuses;
missing source bytes cannot become a complete backup merely through selection.
The ZIP groups database schema, data and metadata separately from the file
categories. Global cluster SQL and deployment credentials are retained for
operator review and manual recovery; import never applies them automatically.

For large installations, operators can deselect file categories and coordinate
an independent storage backup with the mandatory complete database package.
Retained delivery ZIPs are already compressed; bundling them into every export
repeatedly copies those bytes. Use your
storage backup system's incremental or deduplicated snapshots and record the
database archive checksum, image identity and matching storage snapshot together.
Preserve original specifications byte-for-byte. Rehearse restoration into a fresh
database with the matching files before treating a backup as verified.

For frequent recovery of a large production database, operate tested PostgreSQL
base backups with continuous WAL archiving and point-in-time recovery at the
database layer. Keep logical exports for portable copies and pre-update recovery
points; they do not supply WAL-based recovery. PostgreSQL describes these separate
approaches in its [backup guide](https://www.postgresql.org/docs/14/backup.html) and
[continuous archiving guide](https://www.postgresql.org/docs/14/continuous-archiving.html).
This Admin refactor does not configure that infrastructure or its schedules.

The capacity review shows selected file bytes,
record metadata, estimated database/package size, free space and the reserve.
Native capture streams into the final ZIP without a second standalone dump.
Estimates are advisory; actual archive/member/expanded limits and free space
remain enforced during capture. Omitting optional files still needs capacity for
the complete database archive and metadata. It does not bypass package limits.

After verifying independent copies, use **Transfer history → Release this export
package from server storage** to remove old completed export payloads. The
operation's completed state, checksum and journal remain. Retention is explicit:
there is no automatic deletion of backups. Do not remove the transfer directory
to free space; it also owns database selection, recovery journals and file pins.
Imports and restored databases are excluded from this cleanup action.
Export retries and payload release also reclaim private scratch packages left
by a killed writer in that same operation directory; shared files, import
recovery data and other operations are never swept.

For PostgreSQL, a logical dump can be captured from the database service:

```bash
qc_compose exec -T userdb \
  pg_dump --username qc_user --dbname qc_tool --format custom \
  > qc-tool-userdb.dump
```

Adapt names to the effective environment. Store the dump encrypted and verify
it with a restore exercise.

For SQLite, coordinate a quiescent snapshot of the database file and shared
volume. Do not copy a live SQLite file while writes continue unless the storage
backup mechanism provides an application-consistent snapshot.

At minimum, preserve:

- frontend database;
- `INCOMING_DIR`;
- `WORK_DIR`;
- `S3_CREDENTIALS_DIR` if stored outside `WORK_DIR`, in an encrypted, restricted backup;
- `BOUNDARY_DIR` and current-generation pointer;
- `SUBMISSION_DIR` when enabled;
- deployment configuration and secret references (not plaintext secrets).

Final deliverables live under `SUBMISSION_DIR`, with their retained receipts in
`publication_submission`. Keep that directory outside upload/worker cleanup and
on durable storage that supports file and directory synchronization. Restore the
database and its publication files together, then verify the manifest inventory
and recorded checksums before reopening submissions. A successful database restore
alone does not prove that the verified deliverables were recovered. See the
[publication retention contract](../../src/qc_tool/database/SCHEMA.md#retaining-verified-deliverables).

## S3 credentials

S3 source records contain location metadata and an opaque credential reference.
The credentials themselves are in private files under `S3_CREDENTIALS_DIR`, which
defaults to `WORK_DIR/s3_credentials`. They are plaintext operational secrets on
that filesystem; restrict host and volume access and encrypt backups. A database
dump alone cannot restore S3 access.

The frontend creates the directory with mode `0700` and files with mode `0600`.
Both must be owned by the frontend runtime UID. Restore these permissions and
ownership when restoring storage or changing the container's runtime user.
Symlinked directories/files, files readable by other users, malformed files and
credentials for a different source location are rejected. Configure a real
directory or volume mount, not a symlink. Do not put it under static files, an
individual job, incoming deliveries or final publications, and exclude it from
job cleanup. If its parent directories do not exist, provision their ownership
and persistence as part of deployment.

Before reopening S3 work after recovery, restore the credential directory with
the matching database and test registration plus a worker job. Missing credentials
prevent new jobs from being queued. A queued job whose credential file disappears
fails safely when a worker claims it; workers are not sent empty credentials.
A prepared database restore alone does not restore these credential files.

To rotate credentials, revoke the old key at its S3 provider and register the
delivery again with its replacement credentials through the existing S3 API.
Each registration gets its own credential reference, even for an identical
location. Existing historical records retain their original reference. If old
records must remain runnable, an operator can replace the referenced file with
the same host/bucket/prefix and new credentials using a private, complete temporary
file followed by an atomic rename; retain mode `0600` and frontend UID ownership.
Never put keys in shell arguments, logs or tickets. Do not delete files merely
because they are old: check whether any retained source records reference them.
There is no automatic credential rotation or garbage collection.

## Upgrades

The [database guide](../../src/qc_tool/database/README.md) owns models-only
initialization and schema validation. Use the procedure from the same source
revision as the pinned image and record its evidence with the
[release template](../../src/qc_tool/database/RELEASE_TEMPLATE.md).

v3.0.0 has no migration framework, definitions, snapshots or legacy converter.
Its database command cannot upgrade existing tables. A complete schema matching
the candidate models can be retained; a changed schema requires a separately
prepared target and reviewed data transfer. Initial migration definitions are
reserved for a separate 3.0.1-or-later review; this branch supplies no such path.

For a prepared current-schema copy, use the
[manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md). Keep conversion
scripts, original legacy sources and intermediate artifacts in private operator
storage outside the maintained application.

### Maintenance procedure

1. Rehearse the candidate with representative data and boundaries. Verify a
   coherent database/storage backup and restore procedure.
2. Pin matching frontend and worker image identifiers. Render the deployment
   configuration and inspect its target database and persistent volumes.
3. Enter maintenance mode, prevent new writes/uploads, and drain or deliberately
   stop active jobs. Stop frontend and workers so clients and background tasks
   cannot continue writing.
4. Take the coordinated backup. If the schema changes, prepare and validate a
   separate target through the manual restore procedure; preserve the old target.
5. Run the candidate image's read-only `database plan` and `database check`
   against the selected target. Validate retained records and corresponding
   storage. Stop if its schema is partial, foreign or has detected model drift.
6. Only after validation, select the reviewed target and recreate application
   services. Exercise login, permitted/denied access, deliveries, submissions
   and a representative worker job.
7. Leave maintenance mode and monitor. Record image identifiers, backup/restore
   references, target identity and validation results.

```bash
qc_compose config --quiet
qc_compose pull
```

After configuration validation succeeds, enter maintenance and drain jobs.
Stop all application writers:

```bash
qc_compose stop worker frontend
```

Take the coordinated backup described above. Configure only the reviewed target
and inspect it with the pinned frontend image:

```bash
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database plan
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database check
```

Both commands inspect schema without writing application data. `database apply`
is for empty-target initialization; it is not an upgrade or repair command.
A complete current schema makes `apply` a read-only no-op. If validation fails,
keep the services stopped, preserve the target, and review the discrepancy rather
than resetting data or changing the schema to make startup pass.

Continue only after schema, data, storage and application compatibility checks
succeed:

```bash
qc_compose up --detach --remove-orphans --scale worker=4
qc_compose exec frontend python3 -m qc_tool.frontend.manage check --deploy
```

Use the same service configuration and pinned image for validation and the
application. The `run` command replaces ordinary startup and `--no-deps` avoids
launching application services as a side effect. Prevent concurrent deployments
with the deployment runner's environment lock. The repository does not supply a
production deployment orchestrator.

Production startup validates schema read-only. It does not verify restored
business records, filesystem contents or S3 credentials. Keep those checks in
the manual restore/recovery procedure. The first initialization attempt can use
`--traceback`; retain its output in restricted logs and avoid a retry merely to
obtain diagnostics.

## Scale workers

```bash
qc_compose up --detach --scale worker=4
```

Workers atomically claim waiting jobs, so replicas may share a queue. Capacity
planning must include per-worker shared memory, Java/validator memory, embedded
PostGIS, archive expansion, shared-storage throughput, and external S3 limits.

Do not scale the frontend horizontally until background status refresh and
static-file collection responsibilities are moved to dedicated processes and
the database/storage profile supports it.

## Session maintenance

Django database sessions expire logically but rows require periodic cleanup:

```bash
qc_compose exec frontend python3 -m qc_tool.frontend.manage clearsessions
```

Schedule this command through the deployment's trusted job runner.

## User incidents

- Deactivate a compromised account immediately.
- Revoke its personal API tokens in Django Admin.
- Change/reset its password.
- Review role, direct permission, and product grant changes.
- Rotate any leaked S3 or external credentials at their source.
- Preserve audit evidence without copying secrets into tickets.

Changing a password invalidates other password-authenticated sessions when they
next authenticate against Django's session hash. Permission and scope changes
take effect on the next request.

## Boundary retention

Each running job pins one immutable generation. Do not remove old generations
merely because a newer one is active. A pruning process must know that no
running job or retained audit workflow references a generation, enforce a grace
period, and never follow untrusted links.
