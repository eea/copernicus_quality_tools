---
title: Operations
parent: Deployment
nav_order: 2
---

# Operations

Use the same Compose project name, env file, and Compose-file set for every
command. For the examples below, define a shell function for the selected
profile:

```bash
qc_compose() {
  docker compose \
    --project-name qc_tool_app \
    --env-file /secure/path/qc-tool.env \
    -f docker/docker-compose.eea.yml \
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
system. The database references files under incoming/work storage.

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

## Upgrades

1. Read release and migration notes.
2. Back up database and shared data.
3. Validate new image tags in a staging environment with production-like data
   volume and boundaries.
4. Render Compose configuration with `config --quiet` and inspect it.
5. Enter maintenance mode and allow/stop jobs according to policy.
6. Pull images.
7. Recreate services; frontend startup applies migrations.
8. Run `check --deploy` and smoke tests.
9. Leave maintenance mode and monitor.

```bash
qc_compose pull
qc_compose up --detach --remove-orphans --scale worker=4
qc_compose exec frontend python3 -m qc_tool.frontend.manage check --deploy
```

Rollback may require restoring the database and shared volumes; rolling back
only an image is unsafe when a migration is not backward compatible.

## Scale workers

```bash
qc_compose up --detach --scale worker=4
```

Workers atomically claim waiting jobs, so replicas may share a queue. Capacity
planning must include per-worker shared memory, Java/validator memory, embedded
PostGIS, archive expansion, shared-storage throughput, and external S3 limits.

Do not scale the frontend horizontally until background status refresh and
startup migration/static responsibilities are moved to dedicated processes and
the database/storage profile supports it.

## Session maintenance

Django database sessions expire logically but rows require periodic cleanup:

```bash
qc_compose exec frontend python3 -m qc_tool.frontend.manage clearsessions
```

Schedule this command through the deployment's trusted job runner.

## User incidents

- Deactivate a compromised account immediately.
- Revoke its API credential in Django Admin.
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
