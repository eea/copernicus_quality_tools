---
title: Operations
parent: Deployment
nav_order: 2
---

# Operations

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
