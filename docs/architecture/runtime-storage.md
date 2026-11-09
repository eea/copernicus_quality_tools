---
title: Runtime storage ownership
parent: Architecture
nav_order: 13
---

# Runtime storage ownership

Source code, retained evidence, private control state, logs and worker scratch
have different lifetimes. `qc_tool.storage.layout` derives their configured roots
without creating or moving files. Job-specific resolution checks only supported
directory names beneath the configured jobs root. `QC_TOOL_DATA_ROOT` explicitly
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
│   │   └── <canonical-job-uuid>/
│   │       ├── job.json
│   │       ├── result.json
│   │       ├── specification/<original-specification-name>.json
│   │       ├── reports/<original-report-name>.pdf
│   │       ├── outputs/<original-check-generated-files>
│   │       └── logs/
│   │           ├── worker.log
│   │           └── console.log
│   └── submissions/
│       └── product-<id>-<product-ident>/
│           └── specification-<release-id>-<series-key>-r<revision>-<definition-sha256>/
│               └── product-unit-<id>-<unit-code>/
│                   └── submission-<uuid>.d/
│                       ├── input.d/<original-delivery-name>.zip
│                       ├── specification/<original-specification-name>.json
│                       ├── reports/<original-report-name>.pdf
│                       ├── outputs/<retained-check-files>
│                       ├── job.json
│                       ├── result.json
│                       ├── SUBMITTED
│                       └── submission-manifest.json
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

The worker also has its own embedded PostgreSQL/PostGIS cluster under
`/var/lib/postgresql/17/main/` for temporary QC schemas, and validator resources
under `/etf/{config,ds,projects,td,testdata,inspire-registry-resources}/` with
validator uploads/logs/cache beside them. These are worker runtime internals,
separate from the application database and retained delivery evidence.
Ordinary `/tmp/` and validator/Jetty temporary files follow the container's
runtime lifecycle. Application source, bundled recipes and installed assets
under `/usr/local/src/copernicus_quality_tools/` are image/source content,
not administrator-uploaded business storage.

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

## Job and publication identities

New job directories use the dashed UUID exactly as shown in the UI. The shared
`qc_tool.jobs` owner resolves both this versioned layout and retained
`job_<compact-uuid>/` directories with root-level specification/report/result,
`output.d/`, `job.log` and sibling `job.<uuid>.stdout`. Existing files stay at
their recorded locations. Both directory forms for one UUID are an ambiguity
and are refused; readers never select individual files from competing runs.

`job.json` has its own format/schema version and measured execution provenance:
original specification filename and SHA-256, input identity, product/unit facts,
boundary generation and execution times/status. Unknown facts stay null. Its
`producer_layout_version` describes the producing execution, not a command to
relocate retained files. Missing/invalid provenance in a canonical directory is
refused. Historical jobs do not receive invented metadata. Original result,
specification, report and check attachment filenames and bytes are preserved.
New uploads retain their original filename in activation metadata. Older
uploaded versions without that metadata retain their known checksum-based
source filename; the application does not invent an original filename.

New publication parents identify the business product, explicit specification
series/revision, exact executable definition checksum and required unit. Folder
labels are safe bounded slugs; numeric catalog identities and the full definition
checksum disambiguate them. No year is parsed from filenames or inserted as a
grouping level. A year already present in an explicit product/series/unit name
remains part of that name. Product families and specification series must be
configured explicitly; the application does not guess them from similar names.

A specification set revision may update coverage while retaining identical
recipe bytes. Conversely, parallel series within a product can each have a
current revision. The catalog's explicit current selection determines this,
not import date, the most recent job or the lexicographic folder order.
Product pages show selected revisions, retained recipe history and content
fingerprints. Each revision links to its own approved deliveries.

Stored and approved deliveries use the same immutable publication. Approval
changes SQL review state and its event history without moving/copying files.
Only an explicitly accepted, published submission is final for its exact unit
and specification revision. A later pending candidate leaves that approval
intact. A new specification revision has its own units and needs its own
approvals; older approvals remain visibly historical. There is no mutable
`latest/` or `final/` folder whose contents could disagree with review history.
Existing release/unit or release/aoi publication keys and manifests remain
readable without renaming. See [catalog and submissions](product-catalog-and-submissions.md).

## Operational folders inside retained roots

Some small hidden folders exist only while an operation is in progress or after
an explicit administrator action. They are control/recovery records, not another
delivery organization scheme:

| Location | Contents and ownership |
| --- | --- |
| `incoming/<username>/uploads/<opaque-upload-key>/` | Resumable `chunk-00000001.part` files, `.upload.lock`, assembly and registration receipts; coordinated by the upload service |
| `incoming/<username>/uploads/filename-<sha256>/` | Per-filename serialization and overwrite intent; never a final delivery |
| `specifications/.upload.lock` | Serialize immutable version publication and activation metadata |
| `boundaries/.boundary-package.lock`, `.boundary-current` | Boundary publication lock and selected generation |
| `boundaries/.boundary-legacy-backups/` | Retained legacy package handoff evidence where present |
| `boundaries/.qc-tool-boundary-trash/` | Guarded retired boundary generations and recovery data |
| `<storage-area>/.qc-tool-trash/<operation-id>/` | Original quarantined payload and `journal.json` for reversible Storage Admin actions; same filesystem as the source |
| `submissions/.../.submission-<uuid>.pending/` | Submission-owned staging beside the final directory; verified before atomic rename |

Temporary adjacent `.artifact-*.tmp`, `.job-*.tmp`, `.state-*` and specification
staging names are incomplete atomic writes. Their existence does not establish a
successful run, active specification or completed publication. Retained trash,
overwrite receipts, transfer journals, backup packages and file pins must not be
removed by a generic age-based cleanup.

## Lifetimes and consistency

| Namespace | Lifecycle and cleanup boundary |
| --- | --- |
| Incoming ZIPs | Canonical uploaded inputs. Resumable assembly and registration retain inode ownership until a durable registration receipt exists. Replacement has its own recovery protocol. |
| Specifications | Original uploaded bytes and immutable versions; activation is a separate small state record. Never regenerate originals from database JSON or include this tree in scratch cleanup. |
| Boundaries | Immutable generations and one activation pointer. Each job pins one generation through framework-independent `qc_tool.boundaries`; Admin owns upload and guarded retirement. |
| Job files | Retained execution evidence. A result/report directory is not disposable simply because the job is terminal. New runs use the versioned UUID layout; retained legacy paths stay readable. |
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
| `jobs/<uuid>/outputs/`, reports, specification, provenance and results; legacy `jobs/job_<uuid>/` | Durable run evidence; kept in place and pinned for the retained database copy |
| `submissions/.../input.d/<delivery>.zip`, specification, reports, outputs and manifest (legacy `output.d/`) | Durable published evidence; exact inputs and outputs remain covered despite the `input.d` directory name |
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
