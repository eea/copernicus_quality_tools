# Storage browser and desktop connections

**Admin → Storage** opens **Browse files** for application storage locations and
other mounted folders. **File history** groups submitted deliveries, product
specifications and boundary versions. The browser respects protected application
paths and the account's administrator permissions. **Connection**
shows the deployment's SFTP connection details when an operator has configured
them. Showing those details does not create a server or grant SSH access.
With the EEA persistent-storage profile, Storage opens the **Persistent storage**
folder directly; the recorded collections remain available under **File history**.

For an EEA Azure installation, use the optional
[persistent-storage profile](eea-storage.md). **Browse files → Persistent
storage** then opens the real application filesystem at `/mnt`, with ordinary
folder navigation and downloads. Shared frontend/worker paths remain the same;
raw PostgreSQL and private frontend storage stay outside that browser root.
The profile requires an operator-mounted filesystem and matching storage
identity. The default local and EEA named-volume deployments remain available.

For many files or a long transfer, an SFTP client can browse a server share and
download whole folders. SFTP runs over SSH; it is a different protocol from FTP.
Use an SFTP-capable desktop client such as
[WinSCP](https://winscp.net/eng/docs/protocols) or
[Cyberduck](https://docs.cyberduck.io/protocols/sftp/). A Finder-like browser in
QC Tool does not require Finder or Windows Explorer to support SFTP themselves.

## Find deliveries and reference versions

| Task | Open |
| --- | --- |
| Find submitted deliveries | **Storage → File history → Submitted deliveries**. Search by filename, product, unit or submitter. |
| Find approved deliveries | Choose **Approved** in the same library. Current and earlier delivery-plan approvals are identified separately. |
| Find a submission's original files and QC evidence | Choose **Open files** or **Download ZIP** on its row. A published folder means retained evidence, not approval. |
| Find specification history | **File history → Product specifications** starts with current versions. Click a product name for its history or choose **All versions**; originals have direct downloads. |
| Find boundary packages | **File history → Boundary versions** starts with the current package. Choose **All versions** or **Previous** for retained packages, with direct file browsing and ZIP downloads. |
| Find uploads with no submission, unlinked files or logs | **Browse files** opens the existing folder browser. |

Historical submitted records without a publication/review receipt remain visible
as **Historical submission / Approval unknown**. A current upload found at the
old upload path is not advertised as a verified historical original. Missing
files do not remove the submission or catalog revision from the library.

Version libraries read the existing immutable stores and catalog; they create no
second version database or new filesystem layout. **Current** describes the
runtime selection. **Current catalog revision** describes the existing product
release reference; the two are shown separately when applicable. Original
specifications are downloaded as their exact stored bytes, never regenerated
from JSON. Activation, product/boundary uploads and review decisions retain their
existing owning workflows; Storage provides read-only history and file access.

**Product specifications is one versioned collection.** An upload adds a saved
version to that collection. Current, previous and archived versions share the
same history and original-download flow.
The normal version list hides additional installation source files; check
**Include installation source files** when those files are needed. A current
installed source remains visible if it supplies the active specification.
Unfingerprinted source files are labelled as sources, rather than advertised as
extra saved versions. Only proven content identities or the same observed
physical file are merged; matching filenames or sizes are insufficient.

Boundary dates are labelled **Stored / modified** because the existing layout
does not retain a durable upload timestamp for every historical package. Version
IDs are stable identities, not invented chronological version numbers. The
library handles `.versions` and `.boundary-generations` internally, so users do
not need to navigate those folders to find ordinary version history.

## Browse and download in Admin

The main locations show each available storage tree once. Saved specification
versions are in `WORK_DIR/product_definitions`; open the work location and then
its `product_definitions` folder. That child folder does not need a second
top-level location. **Installation files** is a collapsed section containing
specification sources shipped with QC Tool. These sources are separate from
durable uploaded versions, so an application update does not replace user data.
Use **Product specifications** for the combined version history.

The two directories have different roles. An explicit saved version is selected
first; otherwise the configured installation sources provide the fallback.
Archiving a product blocks that fallback. Browsing does not select a version,
copy files between directories or remove either original.

Choose a location in the sidebar, then click folder names to open them. Use
**Up** or a breadcrumb to return to a parent folder. **List** and **Icons** show
the same files; the browser remembers the chosen view on this computer. Search
filters names in the current folder only. The column titles sort the current
folder, with folders first.

**Browse files follows the real folder structure.** Root names and filenames are
the names on the server. Each location card and the **Server folder** address
show its actual server/container path; identically named roots can be distinguished
by that path. **Copy path** copies the current address. **Go to folder** opens a
relative path inside the selected location, and an empty path opens its root.
Opening file information and returning keeps the folder's search, sort and page.
Opening a different folder clears the previous folder's search and retains the
sort order. With focus in the folder view, **Ctrl/Command+A** selects the current
page and **Escape** clears the selection. Text fields retain normal editing.

Use **Download** beside a file, **ZIP** beside a folder, or select items and
choose **Download selected ZIP**. Selection applies to the current page. A
**Download folder ZIP** includes that folder's complete eligible contents,
regardless of search filters. A ZIP preserves relative paths under `files/`
and includes `QC_TOOL_DOWNLOAD_INFORMATION.txt` with exclusions. It is streamed
in chunks without creating another archive on the server. Keep the download
connection open; folder ZIPs are not retained background backups. Single-file
downloads support HTTP byte ranges for clients that resume transfers.

To bound request work and inventory memory, one archive allows 100 selected
paths, 10,000 inventory entries and 32 folder levels. Narrow the selection or
use an SFTP client for larger trees. Files that change after inventory cause the
stream to stop rather than yielding a valid incomplete archive. For a consistent
recovery package, use **Maintenance → Back up & restore**.

## Add other server folders

The built-in locations open the actual working, delivery-upload, published
submission, boundary and specification folders. The work folder includes QC job
folders. Available read-only folders already reachable inside another location
are not repeated as additional drives. Locations with different file-management
permissions, missing mounts and inaccessible child paths remain separate.
Specification sources provided by the application are under **Installation
files**. Saved boundary versions use
`.boundary-generations` and saved specification originals use `.versions`, both
visible at their real locations in the physical browser. For product-oriented
version history, use the single **Product specifications** collection instead.
Old confined file/download links remain supported. Unrelated hidden files and
runtime pointer/lock files remain protected. The frontend
cannot browse unmounted host paths. An operator can mount additional approved
storage read-only and register it in `QC_TOOL_STORAGE_ROOTS`. For example, in a
Compose override using paths appropriate to the host:

```yaml
services:
  frontend:
    environment:
      QC_TOOL_STORAGE_ROOTS: '[{"key":"archive","label":"Archive","path":"/mnt/archive"}]'
    volumes:
      - type: bind
        source: /srv/qc-tool-archive
        target: /mnt/archive
        read_only: true
        bind:
          create_host_path: false
```

Use a unique lowercase key containing letters, numbers or hyphens, a readable
label, and an absolute container path. Do not register server root, application
parents, credential locations, database directories or runtime control state.
The UI does not offer arbitrary host path entry. Missing mounts are shown as
unavailable. The general browser is read-only; the existing guarded Trash
workflow remains limited to eligible delivery uploads and QC job artifacts.

## Choose a connection

| Situation | Action |
| --- | --- |
| The host already has a managed SFTP service | Ask its operator for a restricted, read-only application share and a public-key account. Enter those details in the frontend settings below. |
| A dedicated QC Tool share is needed | Review and use the optional standalone Compose service below. |
| Only a few application files are needed | Download them in Admin Storage; no extra network service is needed. |
| A database backup is needed | Use **Admin → Maintenance → Back up & restore**. Copying a live PostgreSQL directory or SQLite file is not a consistent database backup. |

## Select the share contents

The optional service mounts exactly one **dedicated export directory**. Its
contents appear at `/files` in the client. It does not automatically mount any
QC Tool application volumes. The share and all client operations are read-only;
OpenSSH's [`internal-sftp -R`](https://man.openbsd.org/sftp-server#R) denies
filesystem changes, and Compose mounts the share read-only too. Login provides
no shell, command execution, port forwarding or write access.

An operator must select the directories visible in the share. Do not set the
export root to `/`, `/var/lib/docker`, a complete application volume, `WORK_DIR`,
the frontend private data directory or PostgreSQL data. Read-only access still
reveals any secrets stored there. `WORK_DIR` mixes job output with worker tokens,
S3 credentials, maintenance state, transfer journals and recovery packages.
Some job folders also contain original inputs or credential-bearing source
metadata. The browser's filtered path policy does not apply inside SFTP.

An approved share might contain:

```text
/srv/qc-tool-export/
├── deliveries/       # Reviewed INCOMING_DIR
├── boundaries/       # Reviewed BOUNDARY_DIR
├── publications/     # Reviewed SUBMISSION_DIR, if configured
├── specifications/   # Reviewed original specification directory
└── downloads/        # Explicitly selected job output or prepared backups
```

For bind-mounted application data on a Linux host, an operator can bind-mount
individual approved leaf directories into this dedicated tree without copying
their data. For example, after inspecting `/srv/qc-tool/incoming`, these commands
share only that directory:

```sh
sudo install -d -m 0755 /srv/qc-tool-export/deliveries
sudo mount --bind /srv/qc-tool/incoming /srv/qc-tool-export/deliveries
sudo mount -o remount,bind,ro /srv/qc-tool-export/deliveries
```

This is an operator example, not a command for the provided Docker volume names.
Do not guess host paths for Docker-managed volumes or mount a complete named
volume just to reach one child. The EEA/local layouts split incoming, boundaries,
publication and work volumes; the service-provider layout places them beside a
SQLite database in one volume. Configure a reviewed leaf subpath or a separate
export directory for the actual deployment. On hosts where bind mounts are not
available, place explicitly selected downloads in the dedicated directory.
Nested mounts must exist before starting the SFTP container. Persistent host
mounts, container recreation and reboot ordering belong to the host operator.

Files must be readable by the service account with numeric UID/GID `10001`.
Inspect existing permissions first. Grant read/traverse access only to approved
share content, or use staged copies; never recursively change ownership or make
the application volume world-readable to fix a download. The chroot root is
owned by root in the image; only `/files` is the supplied data mount. OpenSSH
[requires root-owned, non-writable chroot ancestors](https://man.openbsd.org/sshd_config#ChrootDirectory).

Original specifications and snapshots remain unchanged. Downloads do not form a
coherent database/storage backup while jobs are changing files. For a recovery
copy, use the database package workflow or a coordinated storage snapshot.

## Prepare access

The optional profile is in
[`docker/compose.storage-sftp.yaml`](../../docker/compose.storage-sftp.yaml).
It is separate from the normal application stack, binds to host loopback by
default and starts only when the `storage-access` profile is requested. No key,
password, share directory or listener is created by the frontend.

1. Give each maintainer a local SSH key using the organization's normal key
   procedure. Put their **public** keys in a root-owned `authorized_keys` file
   outside the share. Never upload their private keys to the server or frontend.
   A suitable file mode is `0644`; its parent must not be writable by other users.
2. Provision a persistent server Ed25519 host key outside the share, owned by
   root with mode `0600`. Use the organization's host-key management procedure.
   Record its public fingerprint over a trusted channel. The service refuses
   to start without this key and never generates or replaces it on startup.
3. Create a restricted operator environment file, for example
   `/etc/qc-tool/storage-sftp.env`, with absolute paths:

   ```dotenv
   QC_TOOL_SFTP_EXPORT_ROOT=/srv/qc-tool-export
   QC_TOOL_SFTP_AUTHORIZED_KEYS=/etc/qc-tool-sftp/authorized_keys
   QC_TOOL_SFTP_HOST_KEY=/etc/qc-tool-sftp/ssh_host_ed25519_key
   QC_TOOL_SFTP_BIND_ADDRESS=127.0.0.1
   QC_TOOL_SFTP_PORT=2222
   ```

   Do not commit this operator file or the private host key. The file contains
   paths, not login passwords. The SSH username is `qcstorage`.
4. Review the rendered configuration and image. The included Dockerfile builds
   OpenSSH from Debian packages. For production, set `QC_TOOL_SFTP_BASE_IMAGE`
   to a reviewed Debian image digest, build and scan the result, then publish
   and set `QC_TOOL_SFTP_IMAGE` to its reviewed image digest. Refresh the image
   when its base or OpenSSH packages require updates. The service shares no
   application network, credentials or database volumes.

From the repository root, validate before starting:

```sh
docker compose --env-file /etc/qc-tool/storage-sftp.env \
  -f docker/compose.storage-sftp.yaml --profile storage-access config
docker compose --env-file /etc/qc-tool/storage-sftp.env \
  -f docker/compose.storage-sftp.yaml --profile storage-access build
docker compose --env-file /etc/qc-tool/storage-sftp.env \
  -f docker/compose.storage-sftp.yaml --profile storage-access up -d
```

For a prebuilt image, use `up -d --no-build` after setting the reviewed image
digest. Do not use the application's project name for this standalone service.
Its default Compose project is `qc-tool-storage-access`.

## Connect from a computer

Keep loopback binding when using an existing SSH host connection. On the
maintainer's computer, start a tunnel using the existing host account:

```sh
ssh -N -L 2222:127.0.0.1:2222 operator@storage-host.example.org
```

Then open the desktop client with:

| Field | Value |
| --- | --- |
| Protocol | SFTP |
| Host | `127.0.0.1` |
| Port | `2222` |
| Username | `qcstorage` |
| Authentication | The maintainer's private SSH key, kept on their computer |
| Starting folder | `/files` |

Verify the server fingerprint against the operator's recorded fingerprint on
the first connection. The SSH host account and the SFTP share account are
separate. Folder downloads and interrupted-transfer resume depend on the desktop
client; keep a source snapshot unchanged when reproducibility matters.

For a private VPN endpoint instead of a tunnel, an operator can explicitly set
`QC_TOOL_SFTP_BIND_ADDRESS` to its private address and restrict port `2222` to
approved clients at the firewall. Do not use a public wildcard binding merely to
make a connection work. SFTP is its own SSH service; an HTTP reverse-proxy route
does not publish it.

## Show the connection in Admin Storage

Set these **frontend** environment variables to the endpoint maintainers should
enter in their desktop clients, then recreate the frontend normally:

```dotenv
QC_TOOL_STORAGE_SFTP_HOST=127.0.0.1
QC_TOOL_STORAGE_SFTP_PORT=2222
QC_TOOL_STORAGE_SFTP_USERNAME=qcstorage
QC_TOOL_STORAGE_SFTP_ROOT=/files
```

For a tunnel, the host is the maintainer's loopback address and the tunnel is
required. For a private direct endpoint, use its approved DNS name instead.
These display settings contain no credentials and do not check or start the
SFTP service. Leaving the host unset shows setup guidance instead of a working
connection claim. QC Tool administrator login does not grant an SSH key or an
SFTP account; access is provisioned and revoked by the host operator.

## Check and maintain access

Before handing over access, connect with a permitted key and verify folder
listing and a sample download. Check that uploading, deleting, renaming, shell
execution and forwarding are refused, and that the client cannot see credentials,
database files or private runtime state. Test with a second, unapproved key to
confirm it is rejected. Do not test writes against live specification content.

Read the standalone service logs with the same env file/profile and
`docker compose ... logs storage-sftp`. Client file operations are logged by
OpenSSH; log rotation is bounded. Remove a maintainer's public key to revoke new
logins. Stop or restart the standalone service to terminate existing sessions
when revocation must take immediate effect. Keep the recorded host fingerprint
across container replacements; investigate an unexpected fingerprint change.

The browser and this share deliberately provide no arbitrary writes to live
application storage. Importing files, replacing specifications, accepting
deliveries, releasing backup files and removing retained data use their owning
application workflows so database references and recovery evidence stay valid.

## Verify the service image in isolation

The repository includes an integration check using disposable fixture keys and
data. It runs entirely inside one container with no host mounts, no published
ports and no external network. It checks permitted downloads, rejected uploads,
deletion and renames, rejected unknown keys and confinement. It does not start
the deployment service or create deployment keys:

```sh
docker build -t qc-tool-storage-sftp:verification docker/storage-sftp
docker run --rm --network none --read-only \
  --cap-drop ALL --cap-add SYS_CHROOT --cap-add SETUID --cap-add SETGID \
  --security-opt no-new-privileges:true \
  --tmpfs /run:rw,noexec,nosuid,nodev,size=4m,mode=0755 \
  --tmpfs /etc/qc-storage:rw,noexec,nosuid,nodev,size=1m,mode=0755 \
  --tmpfs /srv/qc-storage/files:rw,noexec,nosuid,nodev,size=1m,mode=0755 \
  --entrypoint /bin/sh -i qc-tool-storage-sftp:verification -s \
  < docker/storage-sftp/check.sh
```

The fixture data mount is deliberately writable in this check, proving that the
OpenSSH read-only restriction also rejects writes independently of the production
read-only data mount. All test fixtures disappear with the disposable container.
