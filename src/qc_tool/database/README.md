# QC Tool database

QC Tool **3.0.0 includes migration management**. Committed native Django
migrations define the whole application schema; models describe its current
state. The central database package owns policy, schema/history checks, fresh
initialization and the guarded administrator upgrade workflow. Earlier 3.0.0
installations may have the supported history-free, models-only schema; adoption
is explicit and candidate-only. The application version remains 3.0.0. Future
3.0.1 and 3.1.0 releases add reviewed forward migrations.

## Code ownership

| Package | Responsibility |
| --- | --- |
| `frontend/accounts/migrations/` | Native history for account and access models |
| `frontend/dashboard/migrations/` | Native history for catalog, deliveries, QC execution and publication models |
| `database/migrations/` | Native history for application-wide transfer receipts |
| `database/schema/` | Reusable read-only catalog, field, constraint and strict supported-source inspection |
| `database/deployment.py` | Empty-target initialization and the stable whole-application schema lock |
| `database/migration_engine/` | Read-only graph/history inspection, strict predecessor recognition and Django execution on owned candidates |
| `database/upgrades/` | Compose backup, restored candidate, migration evidence and administrator review |
| `database/transfers/` | Existing PostgreSQL backup/restore, durable runner, file pins and database selection |
| `frontend/dashboard/views/admin_migrations/` | Small HTTP handlers, journey decisions, confirmation forms and presentation; database operations delegate to the shared services |

There is one Django migration graph, one backup engine and one database-selection
mechanism. Frontend and worker continue sharing retained business storage through
the configured storage layout. Upgrade candidates reference the existing physical
files and protect them with durable pins; SQL upgrades do not import or reorganize
that storage. The [runbook](MIGRATIONS.md) describes the ordered handoff.

`schema.SchemaInspector` owns read-only current/historical model inspection.
`deployment.SchemaInitializer` reuses it and adds only explicit empty-target
initialization. SQL expression and index comparison have named owners under
`schema/`; transfer compatibility consumes the same native-type normalization.
Migration history, fingerprints and candidate execution live in separate
`migration_engine/` modules. `upgrades/` composes review, evidence and recovery
without copying the existing backup/restore engine. See the
[module boundaries and remaining priorities](../../../docs/architecture/repository-layout.md#small-modules-and-shared-ownership)
before expanding these workflows.

## Whole-application commands

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage database plan
PYTHONPATH=src python3 -m qc_tool.frontend.manage database apply
PYTHONPATH=src python3 -m qc_tool.frontend.manage database check
```

| Command | Behavior |
| --- | --- |
| `plan` | Read-only schema/history inspection and installed migration plan |
| `apply` | Initialize an entirely empty target using committed migrations; a current managed target is a read-only no-op |
| `check` | Read-only whole-application schema/history readiness check |

Startup checks readiness and never upgrades an occupied database. Development/test
may explicitly opt into empty-target initialization; production initialization
is an operator command. CI and startup never generate migration files. Fresh
initialization creates standard permissions/roles, but no users, products or
deliveries. Administrators upload unchanged original specifications separately.

The **Admin → Maintenance → Database migrations** workflow uses installed code only: ready maintenance,
verified native PostgreSQL backup with retained files, separate operation-owned
restore candidate, strict supported-source verification, Django forward
migrations, verification and explicit database switch. It retains the serving
database, backup, candidate, journals and file pins. SQL migrations do not move
or rewrite original specifications, delivery ZIPs, QC results or publications.
Unknown drift/history is refused. Ordinary `--fake-initial` is not strict schema
adoption; only the reviewed initial adoption procedure may record initial history
on its exact supported history-free 3.0.0 restored candidate.

Read the [migration runbook](MIGRATIONS.md) for source compatibility, recovery,
SQLite boundaries and future release practice. Minor `3.0.x` and major `3.x.0`
labels do not establish schema/storage compatibility. Across incompatible schemas,
recovery needs the previous pinned images and retained data offline; reversing
migrations cannot reconstruct discarded rows or files.

The schema inspector validates required tables, columns, backend types,
nullability, primary/foreign keys, uniqueness and declared constraints/indexes.
This readiness check alone is not strict source adoption or a complete recovery
certification. Native restore separately reconciles complete database inventory;
upgrade verification additionally checks supported history and storage evidence.

Legacy conversion remains manual work outside the maintained codebase. Restore
prepared native archives into separate empty targets using [MANUAL_RESTORE.md](MANUAL_RESTORE.md).
Never initialize a restore target first or fake/reset a serving database.

## Administrative data transfer

The central `transfers` package owns complete native PostgreSQL backups and
bounded portable record packages. The native backup profile preserves the
database's own schema and every row, including password hashes, API credential
digests, sessions, receipts and fields/tables outside the portable model
contract. Source schema drift does not prevent a native backup. It never alters
that source or upgrades the restored schema.

**Admin → Maintenance → Create backup** opens the export page and prepared ZIP downloads.
**Restore from ZIP** opens the separate import page. Every new export
preserves all SQL schema and rows, plus separate schema SQL and PostgreSQL
source/inventory/database metadata. Optional sections, all selected initially,
cover original specifications, boundaries, retained delivery ZIPs, QC artifacts,
publications, PostgreSQL globals and supported deployment configuration with
private S3 credentials, the available worker token, referenced PostgreSQL TLS
files and inert specification/boundary activation metadata. Files use logical
folders in the ZIP while retaining
their original storage identities in the manifest. Selected, omitted, empty,
partial and unavailable components are explicit; missing bytes are never
reported as copied. Original specification bytes remain unchanged. The inventory
does not query ORM models and preserves unlinked historical ZIPs even when the
source schema differs from the installed models.

File review hashes original bytes and measures lossless DEFLATE level-1 output in
one bounded read pass. Beneficial compression is used only within the importer's
expansion-ratio bound; other files, the already compressed native dump and
supplementary metadata use stored ZIP members. The ZIP64 container and manifest
versions are unchanged, with original file sizes, SHA-256 hashes and restoration
identities preserved. All selected contents remain included. Export capacity
uses measured compressed file bytes plus ZIP overhead and an advisory database
size estimate. Actual output limits and the free-space reserve are enforced
while writing; original sizes still govern expanded/member limits. No backup or
section is automatically removed to make room. Physical storage must accommodate
the resulting package; import additionally needs staging and expanded-file
space, while PostgreSQL needs room for the separate database, indexes and
transaction work.

**Import package** also accepts supported older account/application packages
with their existing additive-import contracts. Available local files may include
submitted or unapproved deliveries: transfer does not grant approval or change
QC results. A complete database always contains stored password hashes and
credential digests; selected deployment recovery material can contain plaintext
secrets. Protect the ZIP in encrypted external storage. PostgreSQL-global SQL,
deployment configuration and private credential files are manual recovery
material and never applied automatically. Remote objects, runtime scratch/logs,
private maintenance/transfer journals and arbitrary host files require coordinated
independent backups.

Native restoration uses a unique, per-operation empty database created through
the Admin panel on the configured PostgreSQL cluster. The connection identity
needs database-creation permission. `QC_TOOL_RESTORE_DATABASE` is an optional
operator fallback naming a separately provisioned empty target. Restoration never
drops, resets or overwrites an existing database. Do not initialize the
destination from models before restoring an archive that contains its schema. Restore
uses a single transaction and explicit deployment ownership/ACL/tablespace
remapping; supported client/server majors must match. Restore does not activate
the result. A separate explicit Admin switch verifies the restored copy, current
models, connected records/files and administrator access, then updates a private
deployment-bound selection pointer. Maintenance stays on; the previous database
is retained. Admin rollback is limited to that same maintenance generation before
reopening, so it cannot discard subsequently accepted work. See
[MANUAL_RESTORE.md](MANUAL_RESTORE.md).

**Manage databases** distinguishes the one active database, the configured
original, the previous recovery database, operation-owned restore copies and
other databases on the same cluster. Read-only inspection shows current schema
readiness, table names, database sizes and explicitly approximate PostgreSQL
row statistics; it never reveals credentials or scans every record just to browse.
Saved backup ZIPs are a separate inventory and consume backup-file storage.

An explicit deletion can reclaim an unused operation-owned restore database
without deleting its ZIP, shared application files or audit history. It requires
ready maintenance, exclusive transfer admission, the current selection revision
and a request bound to the exact database copy. Admin provides a direct **Delete**
button without manual name entry or an acknowledgement checkbox; the hidden
destination is validated against the server-owned inventory before calling the
deletion service. The configured, active and previous recovery
databases, unknown copies, connected clients and prepared transactions are
protected. Ownership is bound to the original private creation journal, cluster
fingerprint, PostgreSQL owner/OID and unguessable database comment; a replaced
database is never adopted by name. A managed source copy is also retained while
another present restore copy depends on its source identity; remove unused child
copies first. Durable deletion intent resolves a lost
acknowledgement without dropping a replacement copy. PostgreSQL deletion uses
neither `FORCE` nor session termination and is never automatic. See PostgreSQL's
[DROP DATABASE behavior](https://www.postgresql.org/docs/14/sql-dropdatabase.html),
[database-size privileges](https://www.postgresql.org/docs/14/functions-admin.html#FUNCTIONS-ADMIN-DBSIZE)
and [catalog row estimates](https://www.postgresql.org/docs/14/catalog-pg-class.html).

Portable profiles own dependency validation, explicit account mappings and
create-only additive application imports. Selective accounts exclude credentials,
carry roles/product grants as review proposals, and allow explicit bounded name/email
updates while preserving existing identity and authority; new accounts are inactive. The
portable application profile translates integer business IDs, preserves job and
submission UUIDs and original artifact bytes, and records source identities in
its committed receipt. Occupied current-model databases support conflict-reviewed
additions; existing rows and files are never overwritten. It never initializes, repairs
or upgrades a target schema.

`qc_database.TransferReceipt` is owned by this package and stored in
`qc_database_transfer_receipt`. Its package and operation identities are unique.
It commits in the same SQL transaction as imported records, so a lost runner can
establish whether an import committed before recovering its private filesystem
journal. Source receipts are not replayed as target transfer authority. Operation
journals and maintenance pins live in private persistent storage outside SQL.
Native backups retain receipt rows as database content; restoring them does not
replay their old operations or grant them control of the current transfer.

Portable packages carry an explicit semantic contract version, producer release
and schema descriptor. Compatibility compares meaning and relationships rather
than accepting a release label. Structurally valid unsupported packages are
retained for a read-only report and original-package download; applying them is
blocked. Invalid/damaged included payloads remain rejected. No unknown fields
are silently discarded and no conversion or future reader is inferred. Only
implemented reviewed readers belong in the supported registry. This package
contract is separate from Django migration history. A supported archive reader
does not authorize an unsupported schema upgrade.

The Admin Database landing page runs a fresh read-only schema readiness check on
each visit and displays its time, expected record-contract version and concrete
drift/availability reason. The explicit recheck performs the same inspection.
It starts no schema adoption, repair or scheduled worker; other pages do not run
this landing-page check. SQL and filesystem updates have separate durability
boundaries, so transfer journals and reconciliation remain necessary even when
record changes use a database transaction.

Versioned provenance in the existing receipt JSON supports repeated imports and
re-exports independently of schema migration. See the
[additive import architecture](../../../docs/architecture/additive-record-import.md).

The receipt model is included in committed initial migration history. Earlier
models-only draft databases missing it are not equivalent supported 3.0.0 sources;
never add just that table or fake history to bypass adoption checks. See the
[record-transfer design](../../../docs/architecture/record-transfer-design.md)
for package and filesystem durability boundaries.

## References

| Task | Reference |
| --- | --- |
| Initialize or verify a fresh database | [Migration runbook](MIGRATIONS.md) |
| Restore the prepared database copy | [Manual PostgreSQL restore](MANUAL_RESTORE.md) |
| Review model ownership | [Application schema](SCHEMA.md) |
| Review stored fields and SQL integrity | [Table dictionary](TABLES.md) |
| Review verified evidence and remaining work | [Audit](AUDIT.md), [v3.0.0 migration management](releases/3.0.0.md) |
| Record a production installation | [Release template](RELEASE_TEMPLATE.md) |

## Package layout

```text
src/qc_tool/database/
├── policy.json, policy.py          # Managed release and adoption contract
├── deployment.py                  # Explicit empty initialization and schema lock
├── schema/                        # Shared read-only model/catalog inspection
│   └── strict/                    # Exact source checks, backend expressions and objects
├── migration_engine/              # Native graph, historical state and candidate execution
├── migrations/                    # Central application migration history
├── upgrades/                      # Separate review, evidence, execution and recovery owners
├── apps.py                        # Django management-command discovery
├── management/commands/database.py
├── checks/source.py               # Offline source-layout check
├── checks/schema.py               # Disposable migration-created schema verification
├── models.py                      # Atomic administrative transfer receipt
├── transfers/                     # Versioned records, artifacts and recovery
├── tests/                         # Offline and database regression checks
└── releases/                      # Release evidence
```

`accounts`, `dashboard` and `qc_database` are model namespaces in one migration
workflow. Their committed migrations and Django framework migrations share the
native dependency graph and recorder. The central package adds application-wide
safety gates; it does not replace Django's migration engine.
