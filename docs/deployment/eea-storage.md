---
title: EEA persistent storage
parent: Deployment
nav_order: 6
---

# EEA persistent storage

Use `docker/compose.eea-storage.yaml` **alone** for an operator-mounted Linux
filesystem. It is a complete standalone EEA deployment profile, including the
frontend, worker and PostgreSQL services. The canonical layout separates durable
application files, shared control state, frontend-private state, worker scratch
and per-service logs. Each area is mounted separately; neither application
container receives the whole host root.

Choose this host-storage file or the named-volume `docker-compose.eea.yml`;
do not merge them. Download the one selected file from the reviewed revision.
A protected environment file supplies deployment values, without introducing
another Compose definition. Host sources, writable/read-only binds and
provisioning boundaries remain explicit for operator review. For Rancher,
verify the actual importer/version prerequisites described in
[deployment](index.md#rancher-import) before claiming target compatibility.

**This is a fresh-target deployment configuration.** The maintained profiles use
new `qc_tool_v3_*` named volumes and `postgres17_data_v3`; they do not adopt or
copy older application volumes. PostgreSQL 17 must never be pointed at a
PostgreSQL 14 data directory. Preserve existing volumes, private backups and
recovery data until a separately verified handoff is complete.

## Host and container paths

Provision a new reviewed host root, for example `/srv/qc-tool-v3`, only after
verifying its real mount with `mountpoint` and `findmnt`. A Docker bind mount
cannot establish that the intended device/share is mounted.

| Host path under `QC_TOOL_PERSISTENT_ROOT` | Container path | Frontend | Worker |
| --- | --- | --- | --- |
| `data/incoming` | `/mnt/qc-tool/data/incoming` | read/write | read-only |
| `data/boundaries` | `/mnt/qc-tool/data/boundaries` | read/write | read-only |
| `data/specifications` | `/mnt/qc-tool/data/specifications` | read/write | read-only |
| `data/jobs` | `/mnt/qc-tool/data/jobs` | read/write | read/write |
| `data/submissions` | `/mnt/qc-tool/data/submissions` | read/write | absent |
| `state/shared` | `/mnt/qc-tool/state/shared` | read/write | read/write |
| `private/frontend` | `/var/lib/qc_tool` | read/write | absent |
| `scratch/worker` | `/var/tmp/qc-tool/jobs` | absent | read/write |
| `logs/frontend` | `/var/log/qc-tool` | read/write | absent |
| `logs/worker` | `/var/log/qc-tool` | absent | read/write |
| `private/postgresql17` | `/var/lib/postgresql/data` in `userdb` | absent | absent |

`QC_TOOL_DATA_ROOT=/mnt/qc-tool/data` selects this layout. `WORK_DIR` is the
legacy configuration alias for `data/jobs`, containing retained QC artifacts.
Original specification bytes and activation metadata live in
`data/specifications`; bundled sources remain in the image. Shared state holds
worker authentication and maintenance coordination. Frontend-private state
holds credentials, transfer/backup journals and packages, multipart staging,
SQLite when selected, announcements and static assets. Transfer journals default
to `private/frontend/data-transfer`, while backup/import payloads use the separate
`QC_TOOL_BACKUPS_DIR` child `private/frontend/backups`. Neither is a worker mount. Worker extraction
scratch has a separate capacity budget and is excluded from retained evidence.
Logs use distinct frontend and worker sources even though their container paths
match. Auxiliary validator/cache/database paths inside a worker remain separate
from the persistent application database.

The Admin persistent-storage browser opens `/mnt/qc-tool/data`. Its browser
filters are additional protection; private state is physically outside that
root and is never mounted in workers. Desktop SFTP must export a separate
reviewed read-only tree as described in [storage access](storage-access.md).

## Filesystem requirements and provisioning

The application uses POSIX permissions, hard links, symbolic links, atomic
replacement, file/directory `fsync`, and independent-process `flock`. A local
Linux filesystem on a persistent managed disk is the simplest single-VM fit.
A network filesystem requires testing on the exact service and mount options;
a directory listing alone does not establish compatibility. Keep one frontend
instance. Shared storage does not make the background refresh service safe for
multiple frontend replicas.

After verifying the device/share and filesystem identity, create the table's
host directories using operator configuration management. Set ownership for the
reviewed images' runtime UID/GID. Preserve private directory modes (`0700`) and
credential file modes (`0600`); never use blanket `0777` or recursively change
an existing PostgreSQL directory's ownership.

Provision `.qc-tool-storage-id` **inside every application mount root** in the
table: the five data directories, `state/shared`, `private/frontend`,
`scratch/worker`, and both log directories. Each marker contains the same stable
non-secret deployment identity, for example `eea-qc-tool-v3-production-01`, on
one line. Use a regular single-link marker without group/public write access
(for example `0644`). The application never creates or repairs markers.
PostgreSQL's directory has no application marker; the host independently guards
its mount before allowing PostgreSQL to start.

Do not place one marker only in `data/` or the host parent: those parents are
not the mounted application roots. A missing or mismatched marker on any
role-visible root blocks startup before application writes. Worker read-only
input roots share their markers with the frontend's corresponding mounts.

## Configure and check

Use current supported Docker Compose. Supply matching reviewed frontend/worker
image digests that implement this layout. In the
protected deployment environment file:

```dotenv
QC_TOOL_PERSISTENT_ROOT=/srv/qc-tool-v3
QC_TOOL_PERSISTENT_STORAGE_ID=eea-qc-tool-v3-production-01
```

`QC_TOOL_PERSISTENT_ROOT` is a host path consumed by Compose;
`QC_TOOL_PERSISTENT_STORAGE_ROOT=/mnt/qc-tool/data` is the container's browser
root. The guard validates the resolved role-specific roots, including shared
and private roots outside that browser tree. Use the same Compose project,
environment file and selected standalone file for every command:

```bash
QC_RELEASE_PROJECT=qc_tool_v3_candidate
QC_RELEASE_ENV_FILE=/secure/path/qc-tool-v3.env

qc_compose() {
  docker compose --project-name "$QC_RELEASE_PROJECT" \
    --env-file "$QC_RELEASE_ENV_FILE" \
    -f docker/compose.eea-storage.yaml "$@"
}

qc_compose config --quiet
qc_compose run --rm --no-deps frontend python3 -m qc_tool.storage check
qc_compose run --rm --no-deps frontend python3 -m qc_tool.storage probe
qc_compose run --rm --no-deps --entrypoint python3 worker -m qc_tool.storage check
qc_compose run --rm --no-deps --entrypoint python3 worker -m qc_tool.storage probe
```

Inspect rendered mounts privately; avoid printing rendered environment secrets.
Confirm narrow data mounts, read-only worker inputs, separate log sources and
absence of frontend-private/submission storage in workers. `check` validates
existing directories/markers without creating application state. `probe` uses
its own temporary test files on writable role roots; read-only worker inputs are
validated without writes. Probe success does not certify cross-host locking,
power-loss recovery, throughput or Azure infrastructure.

`QC_TOOL_REQUIRE_MOUNTS=yes` makes canonical startup refuse any required root
that is not an actual mountpoint, including a directory left in the container
writable layer. Private upload staging is safely created under its validated
frontend root only after the layout/identity check.

Standalone named-volume profiles omit the identity contract. Their canonical
entrypoints still run `check-layout` before application imports/writes to
validate existing mount directories and configuration. Empty named volumes are
fresh application roots; they are not implicitly populated from old storage.

## Host startup and restore

Make the host service depend on the actual mount, using
`RequiresMountsFor=/srv/qc-tool-v3` and an explicit `mountpoint --quiet` precheck
(or the equivalent in the deployment's service manager). Account for Docker's
automatic container restart path as well: a Compose unit alone cannot prevent
an existing container restarting before that unit runs. PostgreSQL does not
execute the application's identity guard. Monitor device/share identity,
capacity and mount availability after startup.

For an existing installation, first verify a complete database backup and
matching file backup. Enable maintenance, wait for positive worker quiescence,
then stop application and external writers. Copy files offline into the new
layout under operator control, preserving original bytes, ownership, modes and
required links. Include hidden specification/boundary activation state, worker
authentication, credentials, database selection, transfer journals and storage
pins. Moving only visible files is incomplete. Path-dependent references and
recovery journals require explicit reconciliation; changing environment paths
alone does not translate them.

Restore a verified native PostgreSQL copy into a separate fresh PostgreSQL 17
target using the [manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md).
Never copy a live raw PostgreSQL directory, mount PG14 bytes in PG17, initialize
a populated/restored database, or reset/fake/alter an existing schema.
Production startup performs a read-only readiness check; entirely empty new
installations need an explicit whole-application `database plan|apply|check`
procedure. v3.0.0 remains models-only and supplies no migration definitions.

Before switching traffic, verify schema, retained records/files, original
checksums, version activation, login, permissions and a representative QC job.
Retain the old installation for recovery, with an explicit rollback policy that
cannot discard newly accepted work. Test container replacement, planned host
reboot and coordinated database/file restore. This documentation and local
regression tests do not establish a live EEA deployment or production recovery.
