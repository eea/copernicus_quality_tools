---
title: Runtime storage ownership
parent: Architecture
nav_order: 13
---

# Runtime storage ownership

Source code, retained evidence, private control state, logs and worker scratch
have different lifetimes. `qc_tool.storage.layout` defines their paths without
creating, discovering or moving existing files. `QC_TOOL_DATA_ROOT` explicitly
selects the canonical layout. Without it, existing environment variables and
legacy paths remain supported; a restart never searches another installation
for missing data or performs an automatic storage cutover.

## Container namespaces

The maintained Compose profiles configure this layout:

```text
/mnt/qc-tool/
├── data/
│   ├── incoming/<username>/
│   │   ├── <delivery>.zip
│   │   └── uploads/<opaque-upload-key>/chunk-00000001.part
│   ├── specifications/
│   │   ├── .versions/<product-ident>/<sha256>.json
│   │   └── .state/<product-ident>.json
│   ├── boundaries/
│   │   ├── .boundary-generations/<generation-id>/{raster,vector}/
│   │   ├── .boundary-current
│   │   └── raster/, vector/       # compatibility links to current generation
│   ├── jobs/
│   │   ├── job_<compact-uuid>/
│   │   │   ├── <product-ident>.json
│   │   │   ├── result.json
│   │   │   ├── job.log
│   │   │   ├── <delivery-stem>_report.pdf
│   │   │   └── output.d/
│   │   └── job.<canonical-uuid>.stdout
│   └── submissions/release-<id>-<key>/product-unit-<id>-<code>/
│       └── submission-<uuid>.d/
│           ├── input.d/<delivery>.zip
│           ├── output.d/
│           ├── <retained job files>
│           └── submission-manifest.json
└── state/shared/
    ├── worker.token
    └── maintenance/{state.json,*.lock}

/var/lib/qc_tool/                 # frontend-only persistent state
├── announcement.txt
├── s3_credentials/
├── data-transfer/                # configured QC_TOOL_TRANSFER_DIR
│   ├── database-selection.json
│   ├── execution.lock
│   └── <operation-uuid>/
│       ├── operation.json
│       ├── runner.log
│       ├── files.json            # file restore operations
│       └── storage-pin.json      # retained database file protection
├── backups/<operation-uuid>/
│   └── package.zip               # backup/import payload; separate from journals
├── upload-staging/               # configured Django multipart spool
├── static/
└── frontend.sqlite3              # used only with the SQLite backend

/var/log/qc-tool/                 # distinct frontend/worker mounts
/var/tmp/qc-tool/jobs/            # worker-only scratch mount
└── <compact-uuid>/
    ├── .qc-tool-scratch.json     # ownership, retain flag and process namespace
    ├── .lease                   # held during the entire worker job context
    └── tmp.d/                   # unpacked inputs and intermediate files

/var/lib/postgresql/data/        # application database container only
```

Paths shown for transfer packages and upload spooling are explicit Compose
settings; standalone callers obtain defaults from `RuntimePaths`. Custom paths
require matching persistent mounts. PostgreSQL application records are separate
from worker PostGIS scratch schemas used during QC. Bundled specifications and
application code remain under `/usr/local/src/copernicus_quality_tools` in the
image; local development overlays the checkout read-only.

The frontend writes uploads, specifications and boundaries, publishes submissions,
and reads retained job results. Workers read uploads/specifications/boundaries
through read-only mounts and write job evidence, worker logs and scratch. They
also access shared authentication/maintenance state. Frontend credentials,
transfer recovery journals and publications are absent from worker mounts.
The optional EEA host-storage profile mounts these same owned subdirectories
individually; it does not bind an entire host data tree into every service.

## Lifetimes and consistency

| Namespace | Lifecycle and cleanup boundary |
| --- | --- |
| Incoming ZIPs | Canonical uploaded inputs. Resumable assembly and registration retain inode ownership until a durable registration receipt exists. Replacement has its own recovery protocol. |
| Specifications | Original uploaded bytes and immutable versions; activation is a separate small state record. Never regenerate originals from database JSON or include this tree in scratch cleanup. |
| Boundaries | Immutable generations and one activation pointer. Each job pins one generation through framework-independent `qc_tool.boundaries`; Admin owns upload and guarded retirement. |
| Job files | Retained execution evidence. A result/report directory is not disposable simply because the job is terminal. Flat `job_<uuid>` paths and stdout identities remain stable. |
| Submissions | Verified copy of exact input plus job files/output, with immutable manifest and SQL publication receipt. Submission and review approval remain separate states. |
| Shared state | Worker token and maintenance generation/locks. This is persistent operational authority, not a cache. |
| Frontend state | Credentials, selection pointer, operation journals, file pins and multipart spool. Retained packages use a separate private `backups` subtree; releasing completed export bytes retains journals and recovery authority. Recover these with the application; never expose them as ordinary browsable evidence. |
| Logs | Role-specific operational diagnostics; frontend and scheduler handlers retain their existing daily rotation. Logs are not a substitute for execution results or recovery journals. |
| Worker scratch | Temporary materialization/intermediates. Normal worker context exit removes its owned scratch child. `LEAVE_JOBDIR=yes` records intentional retention and prevents automatic cleanup. |

Atomicity follows the operation, not a common directory prefix. Resumable chunks
and assembled ZIP publication require their existing same-filesystem hard-link
contract. Submission pending/final directories share their destination filesystem
for atomic rename. Maintenance and transfer state retain their POSIX locks,
private permissions, atomic JSON replacement and fsync behavior. Moving scratch
does not change configured QC check identities, parameter meanings or results.

The separation does not deduplicate evidence. Publication deliberately copies
the verified original ZIP and job artifacts. Hard-linking publication bytes to
externally writable input would undermine their independent retention. A future
immutable blob/location registry is a separate design, described as a proposal in
[database records, files and recovery](database-storage-lifecycle.md).

## Database upgrades and retained inputs/outputs

A database release and a storage layout are separate compatibility contracts.
The Admin upgrade restores SQL into an owned database copy, runs the installed
Django migrations there, and keeps business files at their original physical
paths. The source database, complete recovery ZIP and private journals remain
available. Before migration and first selection, review checks original file
checksums and configured absolute roots, including empty storage areas. Changing
a configured root path invalidates approval even when it contains identical
bytes; changing only the directory prefix is not an automatic data handoff.
Deployment mount identity and durability checks remain the storage guard's
responsibility; the migration fingerprint is not a physical-disk identifier.

| Input/output location | Upgrade retention boundary |
| --- | --- |
| `incoming/<username>/<delivery>.zip` | Durable original upload, including unlinked historical ZIPs discovered by full recovery inventory |
| `jobs/job_<uuid>/output.d/`, results, reports and specification snapshots | Durable run evidence; kept in place and pinned for the retained database copy |
| `submissions/.../input.d/<delivery>.zip` and `output.d/` | Durable published evidence; exact inputs and outputs remain covered despite the `input.d` directory name |
| Worker `/var/tmp/qc-tool/jobs/<uuid>/tmp.d/`, legacy job `input.d/` or `tmp.d/` | Temporary materialization/intermediates; excluded from normal business backup and never treated as the canonical original input |
| Partial upload chunks, logs and private control state | Separate operational/recovery policy; not evidence that a delivery or QC result is complete |

Retention pins bind physical roots, relative keys, SHA-256 and sizes. A configured
specification root may also appear in `PRODUCT_DIRS`; matching logical aliases
pin the same physical file once. Disagreeing checksums/sizes or an incomplete
source inventory are refused. Storage Admin cannot declare a pinned file
unreferenced merely because the active database has no row for it. These pins
remain conservative after failed upgrades or retained-copy deletion; removing
them requires a separately reviewed retirement decision.

The guarantee is preservation and verified references, not automatic conversion
of arbitrary future formats. A future path, filename, manifest or binary-format
change needs a reviewed storage compatibility procedure: supported old/new
readers, explicit versioning, resumable copy/verification when necessary, and a
retention period for original bytes. SQL migration cannot recreate an unavailable
historical input or make an old output format readable by a new parser. Release
verification must exercise representative deliveries, historical reports,
publication manifests and exact input hashes with the target images. Original
specifications and uploaded snapshots are never rewritten.

Installed migrations, including `RunPython`, are trusted reviewed application
code. The candidate protects serving SQL; it is not an operating-system sandbox
for arbitrary filesystem or external-service side effects. Post-run checksums
detect an unsupported shared-file change but cannot transactionally undo it.
Supported database migrations keep their effects within SQL. Review external
side effects explicitly and retain an independent coordinated backup/snapshot
before any separately authorized storage transformation.

See the [migration runbook](../../src/qc_tool/database/MIGRATIONS.md) for native
history, maintenance, failure recovery and the explicit selection step.

## Explicit abandoned scratch cleanup

`scratch_storage` defaults to a read-only plan. It neither enables maintenance
nor creates missing scratch storage. Run it with the normal reviewed application
configuration and database access:

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage scratch_storage --job <job-uuid>
```

An eligible item includes its recorded terminal job state, inactivity, byte count
and a review token bound to exact directory/file metadata. The default inactivity
threshold is 24 hours, configurable with `--older-than-hours` and never below one
hour. Apply requires the same reviewed token and ready maintenance generation:

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage scratch_storage \
  --apply --job <job-uuid> --review-token <token> --generation <ready-generation>
```

The command holds the shared maintenance barrier and refuses unknown, waiting or
running database jobs. Filesystem checks also require the exact compact UUID,
recognized private ownership marker, inactive advisory lease, dead owner PID and
process group, same creator PID namespace, no debug-retention flag and no recent
filesystem activity. Traversal rejects symlinks (including root ancestors), hard
links, special entries, excessive depth/count and changed review fingerprints.
Writable shared roots, nonprivate ownership directories and nested filesystems
also remain refused.
Only that single scratch child is removed; no legacy `job_*/tmp.d`, evidence,
specification, upload, publication, backup or recovery namespace is eligible.

Normal frontend containers intentionally do not mount worker scratch. An operator
maintenance container must use the reviewed frontend image/configuration, mount
the exact worker scratch and required private/shared state, and share the target
worker's PID namespace. A separate PID namespace cannot safely interpret the
creator's process IDs. For replicas sharing the scratch volume, entries owned by
other namespaces remain refused. Scratch from a retired namespace remains for
explicit operator reconciliation rather than being declared dead from another
container. Keep debugging snapshots and malformed/unknown trees for review.
The supported cleanup case is an interrupted validator in its existing worker
namespace; recreating the worker container changes that namespace, so its old
scratch is deliberately not eligible for this command.

There is no scheduled TTL sweeper. Abandoned resumable-upload cleanup is also
outside this command: upload chunks, overwrite recovery records, registration
receipts and ownership links need their own coordinated retention workflow.
Deleting files by age alone could invalidate an interrupted upload or recovery.

Deployment recovery metadata records canonical installations as version 2,
including the resolved data, specification, shared state, frontend-private,
scratch, log, transfer, backup, upload-spool and static roots. The version 1 reader
retains its original storage contract for earlier packages. Both versions are
operator-review-only evidence; restoring a ZIP never applies these settings,
credentials or specification/boundary activation metadata automatically. This
metadata version does not change the outer archive format or database schema.

See [deployment storage](../deployment/eea-storage.md),
[storage access](../deployment/storage-access.md) and
[coordinated maintenance](coordinated-maintenance.md) for their operational
boundaries. Persistent storage identity/probes do not prove backup completeness,
cross-client network-filesystem locking or PostgreSQL exclusivity.
