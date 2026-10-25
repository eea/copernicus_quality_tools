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
history through **Database → Export database / Import package** (`/admin/database/`).
The Database landing page owns the curated table browser and maintenance card;
ordinary record editors retain their own Admin mutation routes and maintenance
fence. All new exports use the complete native PostgreSQL profile. Its builder
always includes schema, all rows and database metadata, with explicit additional
section choices. All optional sections are selected initially. Historical
account/application packages retain their typed import readers and operation
history; there are no separate reduced database or account export controls.

Native restores reproduce archived schema and rows in a separate empty database.
Portable imports use validated records and explicit account decisions. They do
not replace an occupied database, repair its schema or provide an arbitrary SQL
editor. Native imports can allocate a fresh destination; activation and
same-window rollback are separate reviewed Admin actions.

The shared importer keeps the three package profiles explicit:

| Profile | Export selection | Import behavior |
| --- | --- | --- |
| Users / accounts (historical portable packages) | Account profiles previously selected by their exporter | Create inactive accounts, reuse existing identities unchanged, skip incoming users, or explicitly update only first name, last name and email on a matching identity |
| Database records / application (historical portable packages) | The supported QC graph and retained files included in the original package | Add new records to the current database, translate integer identities, reuse compatible records and explicitly exclude conflicting branches; keep job/submission UUIDs |
| Complete database package (all new exports) | Mandatory full database schema and rows, including unmanaged fields/tables, password hashes, API credential digests, sessions and receipts; explicit optional file, PostgreSQL-global and deployment sections | Prepare a unique empty database and restore the complete archive; separately review activation; no account mapping; supplemental cluster SQL and deployment secrets are manual-only |

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

Historical application exports derive required accounts from every included foreign key to
the user model, including owners, requesters, approvers and reviewers. They do
not include unrelated account profiles. New complete database exports preserve
every account and its stored credentials without an ORM projection.

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

The unified database ZIP contains a versioned manifest and
`database/data/database.dump` produced by `pg_dump` in custom format. Native capture preserves
the actual database schema and all row fields, including relations outside the
portable model contract. Model drift does not block this read-only backup or
cause the source to be initialized or repaired. A separate
`database/schema/schema.sql` supports inspection; `database/metadata/` retains
the source identity, table/sequence/large-object inventory, database settings and
restore policy. The custom dump remains authoritative and contains schema and
data together. Both are captured from the same database snapshot.

The existing ZIP64 container and manifest versions also support losslessly
compressed file members. File review hashes original bytes and measures raw
DEFLATE at level 1 in the same bounded read pass. An ephemeral compression plan
is attached to each source; it never changes the manifest's original size/hash,
storage identities or reviewed fingerprint. The writer uses DEFLATE only when
it saves bytes and meets the reader's per-member expansion-ratio bound
(1000 by default); otherwise it uses `ZIP_STORED`. The native custom dump and
supplementary metadata remain stored members. Existing stored packages remain
readable, and completed output uses the same resource checks as imported ZIPs.

Optional filesystem categories use stable identities: `specifications`,
`boundaries`, `deliveries`, `artifacts`, and `publications`. They map to readable
top-level ZIP folders while retaining original root/key identities in the
manifest. The version-2 retained-storage contract records selected and omitted
categories, missing roots, availability status and exact per-category counts.
Readers also support the unchanged version-1 storage contract. Collection and
validation never query ORM models, so preservation survives model drift. Missing
selected roots produce explicit unavailable/partial status and warnings, never
a claim that all files were copied. Omitted trees are not opened.

The optional `postgresql_globals` section preserves roles, role-password
verifiers, memberships and tablespace definitions in
`database/metadata/globals.sql`. The optional `deployment_configuration` section
preserves supported runtime configuration, original private S3 credential files,
the available worker token and referenced PostgreSQL TLS files under
`configuration/`. Its deployment JSON also carries inert activation evidence:
known boundary link target strings are read without following them, and original
specification `.state/*.json` bytes are base64 encoded with exact sizes and
SHA-256 digests. Missing state is explicit. Only known relative boundary targets
are accepted; arbitrary symlinks, traversal, source changes, state files above
1 MiB and the configuration's 32 MiB total bound are refused.
These are sensitive manual-recovery materials.
The application never executes the global SQL, applies deployment settings or
replaces credential files during import. Capturing a selected section must
succeed; a privilege error cannot silently produce an incomplete global backup.
Remote objects, arbitrary host files, worker scratch/logs and private
maintenance/transfer control journals remain outside the package.

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
through the selected configuration section or a coordinated protected external
backup where restored sessions or integrations depend on them. Native
restore does not perform schema conversion.

## Explicit activation and rollback

Restoration does not change the active database. A separate reviewed Admin
action verifies the full restored inventory, runtime schema, connected business
records, local artifact bytes and administrator access. The operator reviews
the displayed target and acknowledges storage/credential compatibility. The
request carries a hidden destination validated against the current review;
manual name entry is not required. A changed
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

The database manager also supports a **new reviewed selection** after the
same-window recovery period has ended. This never relaxes quick rollback's
original evidence. The configured original is eligible only with a durable
same-deployment physical-identity record captured before leaving it, or with
the matching retained source OID in an existing private selection pointer.
Managed restored copies need the exact creation OID/owner/unguessable marker
and an explicit first activation approved against the original full archive.
That approval is persisted in a separate private per-operation record before
changing the pointer, so later selections do not depend on retained ZIP bytes.
Unrelated cluster databases and copies with a deletion intent are ineligible.

Every new selection requires ready maintenance, a serialized execution lease,
an unchanged pointer revision, target isolation, current model/record/file
validation and current administrator access. Its review hash includes both
databases' full current native snapshots and linked file evidence. Changes
after review require a new review. Selection preserves both copies and their
divergent records; it does not merge SQL or restore additional files. The
manager distinguishes these database copies from independently removable
saved ZIP files.

An eligible database copy has a direct **Delete** action without name entry or
an acknowledgement checkbox. Its hidden destination is checked against the
server-owned inventory before the exact name is passed to the central deletion
service. Maintenance generation, selection revision, ownership and protected-copy
checks remain enforced; omitting manual typing does not broaden deletion targets.

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

**Database → Export database** opens one complete-database package builder.
**Import package** accepts native and supported historical portable packages and
uses the profile identified from their validated contents. Transfer history
retains earlier operations. Legacy GET links open the unified builder, while old
reduced-scope export submissions are rejected instead of silently broadening
their consent to include credentials. Full restoration and database activation
retain separate reviewed steps.

Uploading identifies the package profile. The page explains the corresponding
restore or additive-import behavior before any execution. Record counts and the next action
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
reuse them. These portable imports retain typed confirmation of the actual
destination. Native restore uses a hidden destination validated against its
review instead, alongside the trusted-source acknowledgement. Known stale
plans are rejected before queueing or pinning.

Export confirmation redirects immediately to its canonical GET operation URL.
Reloading or returning to this URL never resubmits export creation. Progress uses
bounded, same-origin GET polling over saved server progress; status requests do
not execute, retry or cancel an operation. The runner records its current stage
and available byte/item counts in private operation storage, with throttled
updates rather than a journal write for every I/O chunk. Polling resumes after
browser Back/Forward restoration and transient connection failures. Terminal
status changes navigate to the canonical GET operation URL.
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

The detached process owns no HTTP response or browser connection. Server/container
termination can still stop it; saved ownership does not automatically launch a
replacement runner. Explicit recovery checks the recorded operation and retained
state, and an incomplete export can rebuild its ZIP. This does not promise that
the PostgreSQL snapshot or a partly written archive resumes at its old byte offset.
Completed packages remain on persistent storage until explicit release.

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

Defaults cap portable records at 250,000, complete archives at 16 GiB and
expanded files at 64 GiB. Native capture preserves all rows rather than
truncating to a portable record limit. ZIP member, metadata and
decompression-ratio bounds also apply. Record
and major byte limits are configurable; the service reserves free disk space
before staging or restoration. One transfer executes at a time. Historical
account mapping remains paginated. Native capture has no portable record-count
ceiling and does not construct the complete SQL dataset in application memory.
Creation and execution recheck selected-file and native-package capacity.
Historical additive packages require capacity reviewed for their in-memory record
and plan processing; increasing the configurable row cap does not relax any
field, schema, graph, archive or byte-size checks. New full exports default to
all additional sections selected. Administrators can deselect large retained
file categories and coordinate independent storage snapshots to avoid repeated
copies. The full SQL database and its metadata remain mandatory. Native packages
remain subject to the configured byte limits and physical capacity.

`QC_TOOL_TRANSFER_MAX_MEMBER_BYTES` defaults to the configured archive cap, so
increasing the package cap does not leave a hidden 16 GiB limit on a native dump
or delivery ZIP. The export review exposes record/file bytes, native database
and complete-package estimates, measured compressed file bytes, free space,
reserve and all major byte limits. Known file capacity uses measured ZIP payload
sizes and ZIP overhead; the native dump contribution remains an advisory
estimate from PostgreSQL's physical database size. Expanded-total and member
limits continue to use original bytes. Compression does not bypass these bounds
or omit any selected contents. Execution rechecks actual ZIP output growth and
the free-space reserve before writes. Native capture writes the custom
archive directly into its ZIP member rather than keeping a duplicate dump on
the backup volume. The dedicated runner and maintenance fence still own capture.

Native-tool output is drained in 64 KiB blocks; file hashing/copying uses 1 MiB
blocks. PostgreSQL table reconciliation streams COPY output to its digest rather
than constructing a row list, and native capture does not start parallel dump
jobs. Inventory metadata and archive limits remain bounded separately. This
limits application buffers without weakening snapshot or checksum verification.

The download endpoint opens only a completed retained package and never calls
export creation or execution. It serves authenticated GET/HEAD responses with
the package's checksum validator and bounded support for a single byte range, allowing
an interrupted client to request the remaining bytes. Closing a response releases
that response's file handle; it does not remove the package or alter its journal.
Repeated downloads therefore read the same immutable ZIP until explicit release.

Operators may stage an existing local package through `data_transfer stage-file`
with an explicit administrator identity, avoiding HTTP temporary-file buffering.
The same package validation, limits, Admin review and apply confirmation follow.
This is transport staging, not a database-schema conversion path.

Completed export packages can be explicitly released after a verified copy is
stored elsewhere. Release removes only that operation's private payload,
preserves its completed journal/checksum and blocks downloads once release has
begun. An interrupted release can be finished idempotently. Imported packages,
restore-file pins, receipts, provenance and database-selection state remain
outside this cleanup action; maintenance and execution ownership are checked
before release. Nothing automatically expires or deletes backup data.
Retry, cancellation and release can reclaim a killed export writer's private
`.transfer-*.pending` files and older `database.dump` scratch under the execution
lock. Cleanup is confined to the export's own private operation directory and
refuses links or non-private files; it never sweeps import recovery storage.

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
space and its normal database reserve before starting restoration. File restore
capacity uses expanded original sizes, including files that compress well in the
ZIP; retain enough space for staging and recovery alongside them. Compression
cannot guarantee that arbitrary source data fits a deployment's physical volume
or configured archive limit. Selected sections and saved backups are never
silently removed to satisfy capacity.

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
