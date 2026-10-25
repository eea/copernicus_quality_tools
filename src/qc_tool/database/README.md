# QC Tool database

QC Tool **v3.0.0 has a new models-only schema**. Django models are its only
schema definition. [policy.json](policy.json) is `draft` with `baselines: {}`;
there are no first-party migration packages, baseline snapshots, legacy import
commands or released-migration execution paths in this version.

The central database package owns fresh initialization and read-only readiness
checks for the entire application, including Django's account tables. It does
not upgrade, repair, reset or adopt an existing database.

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage database plan
PYTHONPATH=src python3 -m qc_tool.frontend.manage database apply
PYTHONPATH=src python3 -m qc_tool.frontend.manage database check
```

| Command | Behavior |
| --- | --- |
| `plan` | Read-only: reports whether the database is empty, matches current models, or has an incompatible schema. |
| `apply` | Initializes an entirely empty database. A matching existing schema is a read-only no-op. A partial, foreign or outdated schema is refused. |
| `check` | Read-only: validates the managed model schema and required integrity/access paths. An empty or incompatible database fails. |

An explicit `apply` works for fresh development, test **and production** targets.
Startup checks readiness; it never initializes production automatically. Local
Compose opts into development initialization with
`QC_TOOL_INITIALIZE_ON_STARTUP=yes`. CI and startup never generate migration files.
Use fresh disposable targets after changing models. An empty product catalog
does not mean an empty database: account and history tables may still contain data.

The frontend startup check uses `database check --allow-maintenance-recovery`.
The ordinary `database check` remains strict. If an explicitly selected database
is unavailable, the recovery option admits only the maintenance UI after checking
the same ready maintenance generation, retained database identity/schema and a
usable administrator there. It never changes the pointer or either database.
Recovery startup skips development initialization, demo accounts and development
server database checks; a failed selected-database recovery cannot trigger `apply`.

Readiness validates required model structure and declared integrity/access paths.
It does not exhaustively compare field-generated positive-integer checks,
additional constraints, triggers, privileges or storage. A handoff archive has
separate full schema/data reconciliation evidence; the checker alone does not
certify a manually altered database or a complete production installation.

Fresh initialization creates the current tables, standard permissions and roles.
It creates no users, products or deliveries. Administrators upload original
specifications through **Products → Upload specification**; specifications and
uploaded snapshots must never be rewritten.

Legacy conversion is **manual and outside the maintained codebase**. A prepared
native PostgreSQL archive contains the new schema and converted records together.
Restore it into a separate empty database using [MANUAL_RESTORE.md](MANUAL_RESTORE.md).
Do not run initialization before restoring its schema, restore legacy DDL over
this schema, or reset/fake/alter existing databases to simulate a cutover.
Private conversion source/evidence and database copies are excluded from Git.

Initial migration history belongs to a separately reviewed release in **3.0.1
or later**. Its transition from model-created tables must be designed then;
v3.0.0 ships no future migration or automatic adoption mechanism.

## Administrative data transfer

The central `transfers` package owns complete native PostgreSQL backups and
bounded portable record packages. The native backup profile preserves the
database's own schema and every row, including password hashes, API credential
digests, sessions, receipts and fields/tables outside the portable model
contract. Source schema drift does not prevent a native backup. It never alters
that source or upgrades the restored schema.

**Admin → Database → Export database** is one package builder. Every new export
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
contract is separate from database migration history and does not change the
draft schema policy.

The Admin Database landing page runs a fresh read-only schema readiness check on
each visit and displays its time, expected record-contract version and concrete
drift/availability reason. The explicit recheck performs the same inspection.
It starts no schema adoption, repair or scheduled worker; other pages do not run
this landing-page check. SQL and filesystem updates have separate durability
boundaries, so transfer journals and reconciliation remain necessary even when
record changes use a database transaction.

Versioned provenance in the existing receipt JSON supports repeated imports and
re-exports without changing the draft schema. See the
[additive import architecture](../../../docs/architecture/additive-record-import.md).

This receipt is a current draft model addition, **not migration management**.
An installation created from an earlier draft model set is now a different
schema: use a newly initialized disposable target for development and verify it
with the whole-application database command. Do not add the missing table to an
existing developer/production database, generate a baseline, or infer an upgrade
from its `v3.0.0` label. Production adoption remains a separately reviewed release
and operator procedure. See the [record-transfer design](../../../docs/architecture/record-transfer-design.md)
for the supported safety boundaries.

## References

| Task | Reference |
| --- | --- |
| Initialize or verify a fresh database | [Initialization runbook](MIGRATIONS.md) |
| Restore the prepared database copy | [Manual PostgreSQL restore](MANUAL_RESTORE.md) |
| Review model ownership | [Application schema](SCHEMA.md) |
| Review stored fields and SQL integrity | [Table dictionary](TABLES.md) |
| Review verified evidence and remaining work | [Audit](AUDIT.md), [v3.0.0 record](releases/3.0.0.md) |
| Record a production installation | [Release template](RELEASE_TEMPLATE.md) |

## Package layout

```text
src/qc_tool/database/
├── policy.json, policy.py          # Models-only source contract
├── deployment.py                  # Empty-schema initializer and readiness inspector
├── apps.py                        # Django management-command discovery
├── management/commands/database.py
├── checks/source.py               # Offline source-layout check
├── checks/schema.py               # Disposable model-created schema verification
├── models.py                      # Atomic administrative transfer receipt
├── transfers/                     # Versioned records, artifacts and recovery
├── tests/                         # Offline and database regression checks
└── releases/                      # Release evidence
```

`accounts`, `dashboard` and `qc_database` are model namespaces within one database workflow.
Django's migration modules are disabled for all managed application/framework
apps. Native Django `migrate --run-syncdb` is used internally only when the whole
schema is empty; the public operation is `database apply`. It writes no migration
history. Existing schemas never run initialization or its bootstrap signals.
