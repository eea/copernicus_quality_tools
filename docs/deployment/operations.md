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

- frontend login/health response and error rate;
- database connectivity and storage;
- worker and validator health;
- waiting/running job age;
- incoming, work, boundary, and static storage capacity;
- repeated authentication/authorization failures;
- S3 upstream failures by stable error code.

Never log Authorization headers, S3 secrets, raw delivery contents, session
records, or one-time API credentials.

## Maintenance mode

`MAINTENANCE_MODE=yes` returns maintenance responses for non-admin application
paths. Use it to reduce concurrent application activity during a coordinated
database/filesystem operation. It is not a database lock and does not stop
workers by itself.

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

## Upgrades

The [database runbook](../../src/qc_tool/database/MIGRATIONS.md)
owns schema authoring, compatibility, migration-job gates and recovery rules.
This page describes Compose operations for the selected deployment. Read the
runbook from the source revision matching the pinned release image and complete
its [release record](../../src/qc_tool/database/MIGRATIONS.md#release-record)
using the [template](../../src/qc_tool/database/RELEASE_TEMPLATE.md).

Choose the rollout path before applying schema changes:

- **Compatible PostgreSQL expansion:** use the [online rollout
  sequence](../../src/qc_tool/database/MIGRATIONS.md#online-rollout-sequence).
  Keep the old release serving during the bounded migration job; deploy
  compatible code, backfill, and contract only in a later release.
- **SQLite or incompatible operations after the first release:** use the
  maintenance procedure below.
- **First manual cutover:** use a separate target database and the
  [cutover runbook](../../src/qc_tool/database/MIGRATIONS.md#one-time-manual-production-cutover),
  with the [initial deployment commands](index.md#5-pull-and-initialize-the-database).

SQLite upgrades and the manual cutover require a maintenance window.

### Maintenance procedure

This procedure applies after the major-release baseline. The first architecture
cutover uses a **new database and a manual data import**, described in
[Database migrations](../../src/qc_tool/database/MIGRATIONS.md#one-time-manual-production-cutover).
Do not run the new baseline against a pre-release production database.

1. Read the release's migration and compatibility notes. Rehearse with
   production-like data volume and boundaries; verify restore procedures.
2. Pin the new frontend and worker image tags/digests. Render the deployment
   configuration and inspect its database identity and persistent volumes.
3. Enter maintenance mode, prevent new writes/uploads, and drain or deliberately
   stop active jobs. Stop frontend and workers so API clients, admin sessions,
   background refresh and job polling cannot write during migration.
4. Take a coherent database and shared-data backup. Keep the database service
   and persistent volumes available. Pull the pinned images.
5. Inspect the migration plan and run exactly one serialized migration job
   using the new frontend image. Run required release-specific backfills at
   their documented point, then check the migration state.
6. Only after successful migration and validation, recreate application
   services. Run deployment checks, exercise login and permitted/denied access,
   inspect deliveries and submissions, and verify a representative worker job.
7. Leave maintenance mode and monitor. Record the image digests, migration log,
   backup reference and validation results with the deployment.

```bash
qc_compose config --quiet &&
qc_compose pull
```

After configuration validation succeeds, enter maintenance and drain jobs.
Stop all application writers:

```bash
qc_compose stop worker frontend
```

Take the coordinated backup described above and record its recovery reference
before proceeding. Inspect the new image's plan against the release record:

```bash
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database plan
```

Only after the plan is reviewed, apply it and check the migration state. The
second command runs only if the first succeeds:

```bash
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database apply --traceback &&
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database check
```

Complete release-specific backfills and data validation at their documented
stage. Continue only when both commands and the validation succeed:

```bash
qc_compose up --detach --remove-orphans --scale worker=4 &&
qc_compose exec frontend python3 -m qc_tool.frontend.manage check --deploy
```

Use the same service configuration and pinned frontend image for the job and
the application; the `run` command replaces the normal startup command and
`--no-deps` avoids launching application services as a side effect. Prevent
concurrent deployments with the deployment runner's environment lock. The
PostgreSQL command also holds a session advisory lock and bounds DDL lock waits.
The repository validates migrations in CI but does not supply a production
deployment orchestrator.

Production startup runs the whole-application `database check`; it does not apply pending schema
changes. `database check` checks the migration recorder, not the validity of
imported data or manual schema edits. `makemigrations`, `--fake`, and deleting
migration history are not production repair procedures.

If the job fails, keep application services stopped and follow the canonical
[failure and recovery procedure](../../src/qc_tool/database/MIGRATIONS.md#failure-and-recovery).
The `--traceback` option captures the cause on the first attempt; keep its output
in restricted release logs and do not retry merely to obtain better diagnostics.
Resume only after the release's recovery and compatibility criteria are met.

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
- Review role, direct permission, product grant, and region grant changes.
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
