---
title: EEA persistent storage
parent: Deployment
nav_order: 6
---

# EEA persistent storage

Use `docker/docker-compose.eea.yml` with the optional
`docker/compose.eea-storage.yaml` override for a Linux VM whose persistent
filesystem is mounted by the operator. **Admin → Storage** opens
**Persistent storage**, showing the actual application folders under
`/mnt`; frontend and workers use the same files and container paths.

This is a deployment option, not a change to an existing installation. Without
the override, the EEA profile retains its existing Docker named volumes. Adding
the override does not copy their contents. The actual EEA Azure resources,
mounts, permissions and recovery behavior have not been verified here.

## Choose and mount the filesystem

For the current single-VM deployment with one frontend, a Linux filesystem such
as ext4 or XFS on an Azure managed data disk is the simplest fit for QC Tool's
existing POSIX file operations. This recommendation follows the application's
locking, permissions and durable-write requirements; it is not a claim about
the infrastructure EEA currently operates. Follow Microsoft's
[Linux data-disk attachment and persistent mounting guide](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/attach-disk-portal),
using the filesystem UUID when configuring mounts across reboots.

If EEA supplies Azure Files NFS instead, Microsoft documents POSIX permissions
and hard-link support, with network-based access controls. Review its
[NFS protocol and limitations](https://learn.microsoft.com/en-us/azure/storage/files/files-nfs-protocol)
and validate the application's locking, synchronization and recovery behavior
on that exact mount. An SMB or Blob mount is not an interchangeable filesystem
merely because a directory can be listed. Do not infer support for multiple
frontend replicas from a shared storage service.

Use a real mount such as `/srv/qc-tool`, rather than an Azure temporary/resource
disk or a container's writable layer. Before creating any application folders,
verify the mounted device/share and its expected identity on the host:

```bash
QC_TOOL_PERSISTENT_ROOT=/srv/qc-tool
mountpoint --quiet "$QC_TOOL_PERSISTENT_ROOT"
findmnt --mountpoint "$QC_TOOL_PERSISTENT_ROOT" --output TARGET,SOURCE,FSTYPE,OPTIONS
```

Stop if the mount check fails or the reported source is unexpected. Docker bind
mounts cannot establish that the intended Azure storage is mounted: an existing
empty host mountpoint can otherwise look like valid local storage.

## Prepare the application and private folders

Only after verifying the mount, provision this layout through the operator's
normal configuration management:

```text
/srv/qc-tool/                     # QC_TOOL_PERSISTENT_ROOT: mounted filesystem
├── data/                        # shared frontend/worker mount at /mnt
│   ├── .qc-tool-storage-id       # operator-created storage identity
│   ├── qc_tool_boundary/
│   │   └── boundaries/
│   ├── qc_tool_incoming/
│   │   └── incoming/
│   ├── qc_tool_submission/
│   │   └── submission/
│   └── qc_tool_work/
│       └── work/
│           ├── product_definitions/   # uploaded originals and saved versions
│           ├── upload-staging/        # private frontend upload spool
│           └── …                     # jobs, reports and private runtime state
└── private/                     # outside the browsable /mnt tree
    ├── frontend/                # frontend mount at /var/lib/qc_tool
    └── postgresql/              # userdb mount at /var/lib/postgresql/data
```

The existing `WORK_DIR`, `BOUNDARY_DIR`, `INCOMING_DIR` and `SUBMISSION_DIR`
values do not change. Bundled specification sources remain in the image;
uploaded versions remain in persistent `work/product_definitions`.

Give each directory the ownership required by the reviewed image's runtime
UID/GID. Frontend and worker must both access shared application files;
PostgreSQL data belongs to its database UID. Preserve private file modes such
as `0700` directories and `0600` credentials. Do not apply blanket `0777`
permissions or recursively change an existing database's ownership without
reviewing its image and current deployment.

Choose a stable, non-secret storage identity, for example
`eea-qc-tool-production-01`. For the first provisioning only, create
`data/.qc-tool-storage-id` containing that identity on one line, then set the
same value in `QC_TOOL_PERSISTENT_STORAGE_ID`. Retain it with the filesystem
and its recovery record. The application never creates or repairs this marker.
Use 1–128 ASCII letters, digits, periods, underscores or hyphens, starting with
a letter or digit. The marker must be a regular, single-link file without
group/public write access, for example mode `0644`.
Do not replace an existing marker to bypass a failed check; investigate the
mount or configuration. An identity is not a password or an access credential.

The persistent browser root excludes the marker, credentials, transfer and
maintenance journals, locks and database files through its existing path
policy. Raw PostgreSQL and frontend state are separate mounts outside that
root. Other ordinary application folders retain their real hierarchy. The
browser's file operations remain permission-controlled; mounting a filesystem
does not make every file editable.
Preprovision `work/upload-staging` as a private `0700` directory owned by the
frontend runtime UID; the override places large upload spools there instead of
the container's temporary filesystem.

## Select and verify the Compose configuration

Use Docker Compose **2.24.4 or later**: the override's
[`!override` tags](https://docs.docker.com/reference/compose-file/merge/#replace-value)
replace the baseline mount lists explicitly. Use reviewed frontend/worker images that
include the storage guard. In the existing private deployment environment file,
add:

```dotenv
QC_TOOL_PERSISTENT_ROOT=/srv/qc-tool
QC_TOOL_PERSISTENT_STORAGE_ID=eea-qc-tool-production-01
```

`QC_TOOL_PERSISTENT_ROOT` is a host path used by Compose. The override sets
`QC_TOOL_PERSISTENT_STORAGE_ROOT=/mnt` inside frontend and worker. Configure the
same Compose file set for every operation:

```bash
QC_RELEASE_PROJECT=qc_tool_app
QC_RELEASE_ENV_FILE=/secure/path/qc-tool.env

qc_compose() {
  docker compose \
    --project-name "$QC_RELEASE_PROJECT" \
    --env-file "$QC_RELEASE_ENV_FILE" \
    -f docker/docker-compose.eea.yml \
    -f docker/compose.eea-storage.yaml \
    "$@"
}

qc_compose config --quiet
qc_compose run --rm --no-deps frontend python3 -m qc_tool.storage check
qc_compose run --rm --no-deps frontend python3 -m qc_tool.storage probe
```

Inspect the rendered mounts without publishing its secrets. Confirm both
application services use the same `data` source at `/mnt`, and that the private
frontend and PostgreSQL directories are mapped separately. Repeat the probe
with the worker image before admitting work:

```bash
qc_compose run --rm --no-deps --entrypoint python3 worker -m qc_tool.storage probe
```

`check` validates the configured root and expected identity without creating
application directories. `probe` additionally exercises filesystem operations
using temporary test files. A successful probe establishes local capability;
it does not certify cross-host locking, power-loss durability, Azure recovery
or workload throughput. Retain independent backups and run a restore exercise.
The normal entrypoints check storage before starting application work and
refuse missing or mismatched storage rather than creating a local fallback.

## Make host startup depend on the mount

The host service must wait for the real mount as well as Docker, using
[`RequiresMountsFor`](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html#RequiresMountsFor=).
This example
assumes `/srv/qc-tool` has a reviewed persistent mount definition, the checkout
is `/opt/qc-tool`, and the environment file is protected. Adapt it to the EEA
service manager; it is not installed automatically:

```ini
[Unit]
Description=QC Tool
Requires=docker.service
After=docker.service
RequiresMountsFor=/srv/qc-tool

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/qc-tool
EnvironmentFile=/secure/path/qc-tool.env
ExecStartPre=/usr/bin/mountpoint --quiet /srv/qc-tool
ExecStart=/usr/bin/docker compose --project-name qc_tool_app --env-file /secure/path/qc-tool.env -f docker/docker-compose.eea.yml -f docker/compose.eea-storage.yaml up --detach --wait
ExecStop=/usr/bin/docker compose --project-name qc_tool_app --env-file /secure/path/qc-tool.env -f docker/docker-compose.eea.yml -f docker/compose.eea-storage.yaml stop

[Install]
WantedBy=multi-user.target
```

Record and check the expected `findmnt` source as part of host provisioning and
monitor mount availability afterwards. The startup identity guard complements
these host checks; it does not manage or repair the Azure mount.
Also account for Docker's container restart policies: existing containers can
restart when the Docker daemon starts, before this Compose unit runs. Arrange
mount ordering for that automatic-start path as well, or use an operator-owned
restart strategy that admits containers only after the mount check. The
PostgreSQL image does not run the application's storage-identity guard.

## Move an existing installation deliberately

Keep its current volumes and configuration until a separate target is verified.
Create a complete recoverable database backup and matching file backup, enable
maintenance, wait for confirmed quiescence, then stop all application and
external writers. Perform an offline, operator-controlled copy of files to the
newly mounted tree, preserving original bytes, ownership, modes and required
links. Include private credentials, selection pointers and recovery journals;
the public file browser intentionally does not expose all of them.

Restore a verified native PostgreSQL backup into a separate empty target using
the [manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md). A raw
PostgreSQL directory is not a logical backup and must never be copied live.
Use `database check` against a matching/restored database; do not initialize a
populated target, generate migrations, reset tables or automatically adopt a
different schema. Validate database/file references, original checksums, login,
version selection and a representative QC job before explicitly switching
traffic. Retain the former deployment for recovery and coordinate rollback so
it cannot discard newly accepted work.

After cutover, verify **Browse files → Persistent storage** and downloads
through the actual HTTPS ingress, then test container replacement and a planned
host reboot. Configure monitoring for capacity, mount failures and backups.
Keep one frontend instance; the current frontend owns a background refresh
loop. Local regression tests do not replace these production checks.

For a desktop client, use a separate reviewed read-only SFTP export tree as
described in [Storage browser and desktop connections](storage-access.md).
Never export `/srv/qc-tool`, its `data` parent or the complete work tree: SFTP
does not inherit the browser's private-path filters. This storage profile opens
no SFTP port and grants no SSH account or key automatically.
