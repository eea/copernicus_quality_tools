---
title: Admin record transfer
parent: Architecture
nav_order: 9
---

# Admin record transfer

Status: implemented in the working tree. Deployment and a production restore
rehearsal remain operator work. The
[administrator guide](../user-guide/record-transfers.md) describes the UI.

## Scope and identity

The central `qc_tool.database.transfers` package owns native PostgreSQL backups
and typed portable transfers, validation, archive handling and execution.
Django Admin provides selection, review, explicit confirmation and operation
history through **Database → Import & export** (`/admin/database/?tab=transfers`).
The Database landing page owns the curated table browser and maintenance card;
ordinary record editors retain their own Admin mutation routes and maintenance
fence. In the transfer chooser, **Users** and **Database records** are the two
areas, each with Import and Export actions.
**Backups & recovery** is a secondary, expandable area for native database copies,
activation and rollback. No backup profile is selected by default on the landing
page.

Native restores reproduce archived schema and rows in a separate empty database.
Portable imports use validated records and explicit account decisions. They do
not replace an occupied database, repair its schema or provide an arbitrary SQL
editor. Native imports can allocate a fresh destination; activation and
same-window rollback are separate reviewed Admin actions.

Three profiles keep backup fidelity and selective-transfer rules explicit:

| Profile | Export selection | Import behavior |
| --- | --- | --- |
| Users / accounts (portable) | Selected account profiles or explicitly all profiles | Create inactive accounts, reuse existing identities unchanged, skip incoming users, or explicitly update only first name, last name and email on a matching identity |
| Database records / application (portable) | Complete supported QC business graph, its required FK account dependencies and retained local files | Add new records to the current database, translate integer identities, reuse compatible records and explicitly exclude conflicting branches; keep job/submission UUIDs |
| Full database backup (secondary recovery task) | All database schema and rows, including unmanaged fields/tables, password hashes, API credential digests, sessions and receipts | Prepare a unique empty database and restore the complete archive; separately review activation; no account mapping |

A portable application package includes products, original QC definition revisions,
releases and their definition links, expected product units, remote-source
location metadata, deliveries, terminal jobs, published/failed submissions,
submission reviews and conflicts with their event histories. It preserves original
publication bytes while translating local integer identities through a committed
provenance receipt. The [additive import architecture](additive-record-import.md)
documents identity rules, conflict exclusions and job-bound original ZIP access.
Application imports remain insert-only: they never update existing business
rows or replace approvals. The distinct Users profile permits the bounded
profile update described below. Neither profile offers arbitrary table/SQL
import. Per-delivery export selection is not yet supported.

Application exports derive required accounts from every included foreign key to
the user model, including owners, requesters, approvers and reviewers. They do
not include unrelated account profiles. Administrators use the separate Users
export to select profiles independently of QC history.

Portable accounts use source keys only inside the package. Existing target users require
explicit mapping; equal email addresses or usernames never authorize an identity
merge. Application mappings must retain usernames because upload storage uses
those names. Reusing an account does not edit its profile. Source roles and exact
product grants are shown as proposals; the importer does not grant them. New
accounts are inactive and have no usable password or imported administrator
privileges. Administrators enable and authorize them through existing account
controls after reviewing the import.

[`account_import.py`](../../src/qc_tool/database/transfers/account_import.py)
owns planning, application and verification for the Users profile. Each source
key has a typed `import`, `reuse`, `replace` or `skip` decision. The UI calls
`replace` **Update profile**: it changes only `first_name`, `last_name` and
`email`, using an explicit target with a matching username ignoring case. It
does not change the destination PK, username, join date, password, activation,
staff/superuser flags, roles, permissions, product grants, tokens, sessions or
connected history. Skipping excludes only that incoming profile; account-only
packages contain no dependent delivery/job graph. At least one profile must
remain selected.

Portable profiles exclude passwords, personal access tokens, sessions, Django
infrastructure identities, worker addresses and remote storage credentials. S3 records carry
locations, not remote objects or secrets. Provision destination access separately.
Use native database backup together with the deployment's secret/storage backup
procedures for disaster recovery. Existing table exports remain reports, not
import packages.

## Native PostgreSQL archive

The **Full database backup** ZIP contains a versioned manifest and
`archive.dump` produced by `pg_dump` in custom format. Native capture preserves
the actual database schema and all row fields, including relations outside the
portable model contract. Model drift does not block this read-only backup or
cause the source to be initialized or repaired. It is one database's logical
backup; PostgreSQL cluster roles/tablespaces, files, S3 objects and environment
secrets require separate protected backups.

The frontend image packages reviewed PostgreSQL 14 clients from the signed PGDG
Trixie repository for AMD64 and ARM64. Native operations require client/server
major agreement; a newer client is not assumed to produce a dump restorable into
an older target. Build arguments pin the client major and package version.

Native import accepts the QC Tool package contract from a trusted administrator.
`pg_restore` executes schema SQL, so a checksum is corruption detection rather
than a trust decision. The Admin action allocates a unique empty database per
operation on the configured PostgreSQL cluster; browser input cannot choose an
arbitrary target name. The database identity needs creation permission.
`QC_TOOL_RESTORE_DATABASE` is an optional preprovisioned-target fallback for
operators. The serving database and occupied targets are refused. Existing
databases are never dropped, reset or overwritten. A full archive supplies its
own schema; no model initialization runs before it.

Restoration uses one transaction with `--no-owner`, `--no-privileges` and
`--no-tablespaces`. All account/role/grant rows remain intact; PostgreSQL object
ownership, database ACLs and physical placement are deployment responsibilities.
Imported receipt rows are backup content and never replay old operations or
become authority for this transfer's control journal. Interrupted/uncertain
restoration requires destination reconciliation before another attempt.
Native tools inherit the runner's execution lease: a surviving child keeps
competing execution/cancellation blocked after runner death. Target inspection
also rejects other active clients and prepared transactions before treating a
database as empty or recovered.

Private packages and journals use `0700` directories and `0600` files. Downloads
remain administrator-authorized, non-cacheable and protected by the deployment's
HTTPS ingress. Native ZIPs contain sensitive authentication state and are not
encrypted by the application; retain them in approved encrypted external
storage. Preserve the original `DJANGO_SECRET_KEY` and required credential files
separately where restored sessions or integrations depend on them. Native
restore does not perform schema conversion.

## Explicit activation and rollback

Restoration does not change the active database. A separate reviewed Admin
action verifies the full restored inventory, runtime schema, connected business
records, local artifact bytes and administrator access. The operator must type
the displayed target and acknowledge storage/credential compatibility. A changed
administrator credential requires explicit target-administrator authentication;
raw passwords never enter journals.

Activation persists `database-selection.json` in private shared transfer storage,
bound to the configured primary database/host/port/user. It records a revision,
active and previous names, maintenance generation and non-secret verification
evidence. Every frontend must share that storage and configuration. The default
PostgreSQL adapter follows the pointer at connection boundaries; an existing
transaction retains its connection until completion. HTTP requests and lazy
response streams freeze their selected database to prevent mixed reads during
activation. Explicit aliases stay pinned, and Django's temporary test database
overrides never follow a deployment pointer.

Maintenance remains on. Signed operator cookies retain the authentication
database and revalidate its account/roles/password hash on each request, keeping
the source administrator available for recovery. Product managers cannot use a
cookie from another database. Same-window source-admin sign-in is also available
if the selected copy cannot be reached. Reopening requires valid administrator
access in the selected database and ends those signed maintenance credentials.

The reviewed **Switch back** action is available only while the same maintenance
generation remains on. Once normal work resumes, automatic rollback is refused:
the databases may have diverged. Both databases remain intact; no restore,
activation or rollback deletes their data.

## Portable archive contract and original evidence

A package is a bounded ZIP containing a versioned application manifest, one
strict JSON record document, and an allowlisted artifact inventory. Each member
has an exact path, size and SHA-256 digest. The application manifest carries the
package UUID and installed model contract fingerprint. Hashes detect corruption;
they do not authenticate the source. Only import packages from a trusted
administrator over a trusted channel. Packages contain private user information
and need protected storage and transport.

The archive reader rejects duplicate JSON keys, unexpected members, duplicate or
case-colliding paths, traversal, symbolic links, special filesystem objects,
unsupported resource fields, excessive expansion, excessive records and unknown
versions. Package-supplied resource names never select Python models or code.
Original product specifications also pass the installed specification safety
validation before becoming available to QC execution.

Retained files include verified local delivery ZIPs, available job inputs and
outputs, published submission trees and original specification bytes. An original
specification cannot be reconstructed from its JSON database field: the digest
identifies its original bytes. Publication manifests and all files covered by
their immutable inventory remain byte-for-byte unchanged. Missing publication
files or required local uploads block transfer. Already missing optional historical
job files produce warnings. Runtime service logs, maintenance state, unrelated
scratch data and private credential directories are excluded. A log that is itself
part of a publication's immutable inventory remains part of that evidence.

Additive imports preserve immutable specification versions and leave current
specification activation and boundary generations unchanged. Existing
storage files may be reused only when their exact bytes match. Different bytes,
unsafe parents or a conflicting activation block import. Specifications and
uploaded snapshots are never rewritten.

## Review and maintenance ownership

The transfer chooser at **Database → Import & export**
(`/admin/database/?tab=transfers`) separates **Users** from **Database records**. Users
export offers all profiles or selected profiles through the searchable native
Admin picker. **Database records** export fixes the scope to the supported connected
application graph. The expandable **Backups & recovery** area offers a fixed
full-database scope, separate restoration and database controls. Transfer history
reopens each operation in the area identified by its profile. Legacy deep links
remain supported.

Uploading identifies the package profile. A package opened from another area's
upload form moves to its matching area with an explicit notice before import;
it never becomes a silent database restore. Record counts and the next action
stay in the main flow; hashes and operation diagnostics are expandable details.

Users import compares incoming and existing names/email and offers the allowed
per-user actions. Application import reviews ownership mappings, record
conflicts and retained delivery files. **Save choices and review** validates the
current decisions together. Pagination saves the current user-choice, mapping
or conflict page before moving. Unsaved choices disable import in the browser;
the server also detects changed posted decisions and requires a new review
before applying them.

Choice saves carry `expected_plan_hash`. `service.plan_import` checks it against
the stored plan while holding the execution lock, preventing a concurrent
administrator's newer choices from being overwritten by an older page. Saved
user choices persist in the operation's core plan; revalidation and execution
reuse them. The typed confirmation names the actual destination. Known stale
plans are rejected before queueing or pinning.

Progress uses bounded, same-origin GET polling. Status changes navigate to a
canonical GET operation URL, so a rendered POST response is never resubmitted.
Recovery is offered only after the runner lock is free; a startup grace avoids
mistaking a newly queued process for an interrupted one. The maintenance page
preserves a validated local return link to the current transfer.

Export preview and import planning require maintenance readiness. Uploading a
package may happen earlier; it only creates private staging files. Readiness is
rechecked immediately before enqueueing an operation, including positive worker
acknowledgements. A reviewed export hash covers the selected records and file
bytes. An import plan hash covers the package, mappings and user/conflict
decisions, destination fingerprint and supported storage inventory. Execution
repeats validation; a changed source, package, destination or maintenance
generation requires a fresh review.

A durable pin beside maintenance state names the transfer UUID, kind and
maintenance generation. Enqueueing owns the maintenance control lock and drained
activity barrier. While pinned, enabling/disabling/rechecking maintenance and
worker retirement cannot change that generation. A dedicated background
`data_transfer run UUID` process owns the transfer execution lock and the
maintenance barrier. It does not use the paused QC worker pool. Closing the
browser does not terminate the operation. Multiple frontends must share the same
private persistent work directories and working POSIX locks.

A process exit, image restart or elapsed time never releases maintenance. Admin
shows the active transfer and provides retry/cancel controls; CLI recovery uses
the same service. Cancellation is permitted only when there is no committed
import and storage rollback is known to be safe. An uncertain commit or unresolved
filesystem ownership requires recovery before maintenance can resume. Finishing
or cancelling a transfer leaves maintenance enabled; resumption remains a
separate deliberate administrator action. This barrier coordinates QC Tool
writers. Operators must isolate unrelated SQL writers and external filesystem
writers themselves.

## Portable atomic import and crash recovery

The application importer validates strict field types, complete FK closure,
catalog/release identity, terminal work, publication evidence, unit selection,
review/conflict history and database constraints. It never repairs, deletes or
updates existing business records. It creates the selected graph in one database
transaction, resets PostgreSQL sequence positions forward where necessary,
checks constraints and commits a unique `qc_database_transfer_receipt` in that
same transaction.

The Users importer uses that same transaction and receipt workflow. On
PostgreSQL it locks the account/authentication and receipt tables, recomputes
the exact reviewed plan, then creates selected accounts or applies the three
allowlisted profile fields. Streamed private authentication digests verify that
unrelated accounts and existing credentials/access remain unchanged. A receipt
failure rolls back profile updates and new accounts together. Receipts retain
the exact decisions, source-to-local identity mappings, created/updated/skipped
keys and separate created/updated/reused counts. Recovery verifies this summary
and committed authentication evidence without reapplying profile updates.

Files and SQL cannot share a native transaction. The importer first publishes
verified immutable files using exclusive creation on the destination filesystem.
A private write-ahead journal records inode/hash ownership before publication.
Precommit failure rolls back database rows and removes only files demonstrably
created by that operation. Identical pre-existing files are never owned or
removed. A crashed process can replay the journal; uncertain ownership remains
blocked. Empty directories or private temporary files can remain after a process
is killed between directory creation and journalling; they never authorize record
creation or overwrite existing data.

Private temporary copies live under each configured storage root's
`.record-transfer-staging` directory, outside signed publication and job trees.
An abrupt crash can leave unreferenced scratch files there. They do not become
package members or database references. If cleanup cannot establish ownership,
rollback keeps maintenance held for operator inspection; never sweep an active
operation's staging files.

The SQL receipt closes the crash gap between database commit and filesystem
status persistence. Retrying a committed operation verifies its imported records
and files, then completes the journal without repeating inserts or profile
updates. File recovery after a committed receipt never rolls back files
referenced by committed rows.
A lost COMMIT acknowledgement is treated as uncertain until SQL positively
resolves the receipt. A different operation cannot reuse the package UUID to
import it twice.

The filesystem journal contains operation metadata, plans and private packages;
SQL receipts contain package/plan digests, confirming actor and the profile's
verified insertion/mapping/update summary. Portable payloads exclude credentials;
native database archives retain stored credential hashes and sessions as
described above. Keep both kinds of state during recovery. Do not remove a pin
or edit its JSON to bypass an error.

## Schema evolution and release boundary

Portable package format version and model contract fingerprint are separate from QC Tool
release labels. The fingerprint includes supported models, fields, constraints,
domain validation source and datetime policy. In particular, publication
microseconds are preserved exactly; naive and timezone-aware installations cannot
silently reinterpret historical timestamps. Unknown contracts fail closed rather
than dropping columns or applying guessed defaults.

A future version that changes the contract needs an explicitly reviewed compatible
reader and fixture tests, or the documented native database upgrade/recovery
procedure. This implementation contains no speculative schema converters,
first-party migrations or automatic adoption mechanism. Supporting a historical
portable package must never mean executing its SQL or disabling current evidence
checks. Native archives preserve their source schema; they do not supply a
cross-version schema-upgrade mechanism.

The v3.0.0 database policy remains `draft` with empty baselines. The new transfer
receipt is a current Django model, so databases created from an earlier draft
model set are incompatible. Use a fresh disposable database to verify this work;
there is no automatic upgrade of an existing development or production database.
The reviewed migration-management transition belongs to v3.0.1 or later and is a
separate change. See the [database policy](../../src/qc_tool/database/README.md).

## Resource bounds and operation

Defaults cap portable records at 250,000, compressed archives at 16 GiB and
expanded files at 64 GiB. Native capture preserves all rows rather than
truncating to a portable record limit. ZIP member, metadata and
decompression-ratio bounds also apply. Record
and major byte limits are configurable; the service reserves free disk space
before staging or restoration. One transfer executes at a time. Account mapping
is paginated and export selection uses the existing searchable Admin widget.
The export review counts the complete graph in SQL before serializing records,
using the same account-dependency selection as the snapshot. Over-limit reviews
show exact counts and offer an explicit link to review a full backup in Admin,
preserving the file choice. This never silently changes an additive record
transfer into a database restore. Creation and execution recheck capacity.
For larger recovery datasets, use the native PostgreSQL backup workflow in
Admin. Additive packages require capacity reviewed for their in-memory record
and plan processing; increasing the configurable row cap does not relax any
field, schema, graph, archive or byte-size checks.

The private operation journal keeps additive replay decisions and the included
recovery graph, with a digest of the complete reviewed core plan. It does not
duplicate pending record contents or the complete committed result. Admission
and execution rebuild the core from the verified package, compare it with the
review, and check destination freshness before applying anything. The SQL
transfer receipt retains the complete committed audit and verification data;
recovery reads that receipt. Existing full journals remain readable. The
32 MiB private-journal bound is unchanged, and no package or receipt fields are
removed to fit it. Persisted provenance uses its separate stable ledger bound,
so changing portable admission capacity does not invalidate committed history.

Production reverse-proxy body limits, timeouts, shared filesystem capacity and
retention must be configured for the deployment. Preview hashes read retained
files; staging validation also reads the complete package. Large archives can
therefore exceed an interactive HTTP timeout even though execution itself runs
in a separate process. No background operation automatically deletes exported
private packages. Define and monitor retention; remove only terminal operation
packages after confirming no active maintenance pin or recovery depends on them,
and preserve SQL receipts and the operation journal as the audit trail.

The private-file reserve does not certify capacity on the PostgreSQL server.
Provision the separate native target for restored data, indexes, transaction
space and its normal database reserve before starting restoration.

## Verification and supporting guidance

Regression tests cover isolated SQLite and PostgreSQL targets, selected-account
privacy, graph/identity preservation, original evidence, malformed archives,
read-only planning, stale review rejection, rollback, durable ownership, duplicate
receipts, interrupted commit/journal recovery, administrator authorization, CSRF
and maintenance fencing. CI discovers these through the existing database and
frontend integration suites. No product specification is changed by the tests.

The transaction boundary follows Django's
[atomic transaction semantics](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).
Native full recovery remains covered by PostgreSQL's
[backup documentation](https://www.postgresql.org/docs/14/backup.html) and
[pg_dump](https://www.postgresql.org/docs/14/app-pgdump.html), together with the
QC Tool storage and secret backup runbooks. Native integration verification
uses disposable PostgreSQL databases and checks complete schema/row recovery,
credential-hash preservation, target refusal and interrupted-operation safety.
