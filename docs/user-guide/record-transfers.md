---
title: Import and export database
parent: User guide
nav_order: 5
---

# Import and export database

Open **Admin → Maintenance** (`/admin/maintenance/`) and choose one of two pages:

| Task | Use it to |
| --- | --- |
| **Create backup** | Select export contents, follow backup progress and download ZIPs from **Prepared backups** |
| **Restore from ZIP** | Upload a ZIP, review its contents and follow the import or restore |

The pages are separate: `/admin/maintenance/backups/export/` and
`/admin/maintenance/backups/import/`. Choose **Create backup** to select contents,
review the package and prepare a ZIP for download. Choose **Restore from ZIP** to upload a ZIP, prepare a
separate destination, restore it and review whether to use the restored database.
A restore never selects that database automatically. Each page keeps its own
task history and return links. Prepared ZIPs appear on **Create backup**, including
older backups outside the recent task list.

Database inspection has its own **Admin → Database** direction (`/admin/database/`).
**Tables & records** opens a focused table directory. Open a table, then a
record to inspect its details and connected information. **Back to tables** and
**Back to [table]** retrace that path. Account and permission records retain their
**User management** navigation.

**Back to Maintenance** returns to maintenance controls. An open task returns to
its export or import page.
The title identifies its current step, such as **Backup queued**, **Review
database restore** or **Restored database ready**. Older
`/admin/database/?tab=...` and `?tab=history#backup-files` links still open the
corresponding workflow; old combined backup/history pages open **Create backup**.
Only QC Tool administrators can use these controls.

## Progress and waiting states

Submitting a backup, import, database switch or cleanup shows a spinner and the
next step. Submit once and keep the page open until its result appears. Uploading
a ZIP and reviewing large file inventories can take time. Once an export or
restore has been queued, processing runs on the server; leaving or reloading its
progress page does not stop it. Return to its export or import page to see the current
stage and processed file or byte counts, then download a finished ZIP from
**Prepared backups** on the export page.

If another action owns maintenance, a waiting panel checks its status
automatically. When it finishes, choose **Refresh this page** to review the
current state before trying again. Status checks never repeat a failed action.
A transfer that stopped or needs recovery is labelled **Needs attention** rather
than shown as running. Open its details for the available recovery steps.

If a connection fails, the page labels its progress as the last reported state
and offers **Try automatic updates again** or **Check again**. Automatic checks pause in
hidden tabs and resume when you return. Expired sessions, unavailable status and
repeated failures have explicit refresh or sign-in guidance. Maintenance being
**On** means changes are paused; a spinner appears while work or status checking
is actually in progress.

## Databases, backup files and transfer history

QC Tool uses **one active database** for accounts, permissions and records.
Restoring a full backup creates a separate PostgreSQL database copy. The copy
remains separate until an administrator reviews and confirms a switch. A saved
backup ZIP is a file, and a task entry records an import or export;
neither is another active database.

The separate advanced database manager (`/admin/maintenance/backups/?tab=databases`)
shows the active name, available
copies and their current database sizes. Open a database title to check compatibility
and see its tables with PostgreSQL row estimates, without selecting it or
changing its records. Estimates can be stale or unavailable after a restore.

To use another supported copy, turn on maintenance, choose **Review switch**,
review the current and proposed database names, and confirm **Use this database**.
The review checks the copy's identity, current SQL data, schema, shared files and
administrator access. A newly restored copy first needs verification against its
original imported ZIP. Previously approved copies and the original database use
a fresh review when selected again. Switching keeps both copies and does not
combine their records. Maintenance stays on so the administrator can check the
selected installation before reopening it; sign-in may require an account from
the selected database. Immediate **Switch back** remains a separate recovery
control restricted to the same maintenance session.

An unused, QC Tool-owned restore copy offers **Delete**. This button permanently
removes the displayed database copy; you do not need to type its name. QC Tool
checks that the request still identifies that copy before deleting it.
The active, configured original, previous recovery database and copies needed
as identity evidence for another retained restore are protected. Unknown or
changed database identities and copies with connected clients cannot be removed
through this interface. Shared application files and saved backup ZIPs remain.

Open **Create backup → Prepared backups** to download or delete completed export
ZIPs. The list shows available files, their actual sizes and source databases.
Each backup has **Download** and **Delete** controls;
its title opens the details. **Delete** removes one saved export after confirmation;
its history and checksum are retained. Import packages remain available for
restore and recovery. Deleting a ZIP releases backup-file storage; deleting a
database releases PostgreSQL storage. These may be different volumes.

## Export a complete database package

Every new export includes the complete PostgreSQL database: its native schema,
every table and row, password hashes, API credential digests, sessions,
permissions, transfer receipts and database metadata. There is no separate
reduced records-export mode. Native capture also preserves fields and tables
outside the current QC Tool model contract, so an older source schema can be
backed up without altering or repairing it.

All additional sections are selected initially. Choose which to include:

| Section | Contents |
| --- | --- |
| Original product specifications | Original configured specifications and uploaded immutable snapshots, unchanged |
| Boundary packages | Retained raster/vector boundary files and immutable generations |
| Retained delivery ZIPs | Available local delivery ZIPs, including unlinked historical uploads |
| QC results and artifacts | Retained job reports, result documents and attachments |
| Published submissions and receipts | Retained publication trees and their original manifests |
| PostgreSQL globals | Cluster roles, stored role-password verifiers, memberships and tablespace definitions for operator review |
| Deployment configuration and credentials | Supported runtime settings, S3 credentials, worker token, referenced PostgreSQL TLS files and inert specification/boundary activation metadata |

The database itself is mandatory. Deselecting every additional section still
exports all SQL schema, rows and database metadata. Selecting a section cannot
recover missing files or fetch remote S3 objects. The review distinguishes
included, empty, omitted, partially available and unavailable sections; inspect
its warnings before treating the package as a complete recovery copy.

1. Open **Maintenance → Create backup**. If maintenance is off, follow the
   prompt to turn it on and wait for QC work to stop.
2. Choose the optional contents, then select **Review backup**. Options are
   grouped into **Application files** and **Server recovery settings**. The
   database is always included; clear all optional contents for a database-only ZIP.
3. Check section availability, the destination capacity and any exclusions.
   Changing the selection requires another review.
4. Choose **Create backup ZIP**. Progress updates automatically; use
   **Download ZIP** when preparation finishes.

The page follows **Choose contents → Review backup → Prepare & download**.
Section navigation and recovery tools stay outside this flow. Detailed
record/file inventories, capacity limits and technical metadata are expandable.
Missing or partially available sections remain visible in the review.

Package creation runs on the server after confirmation. Reloading, using Back,
opening another Admin page or closing the browser does not stop it. Return to
**Create backup** or bookmark the operation's link. The page reads saved
progress, including the current stage and available byte/file counts; returning
to it does not start another export. Temporary status-connection failures do not
cancel package creation.

When complete, **Download ZIP** links to the prepared ZIP. The same
link remains available in **Prepared backups** until an administrator explicitly
deletes the ZIP. Closing or interrupting a download leaves the saved file
available; downloading it again does not run the export again. A compatible
browser or download client can resume from this link while signed in as an
administrator.

Completion separates **Backup notes**, including unavailable-file warnings,
from **Not included in this ZIP**, which lists items requiring separate backup.
Check both before relying on the package for recovery.

Before a ZIP becomes available to download, QC Tool reopens it with the import
reader and verifies its complete inventory, file checksums and size limits.

The installed PostgreSQL dump client and source server must have the same major
version. This feature performs a logical backup, not a database-schema upgrade.

## Package layout and credentials

The ZIP separates PostgreSQL recovery material from application files. Its
versioned manifest records the selected sections, file sizes and SHA-256 hashes;
original specification and publication bytes are never rewritten. Schema SQL is
provided for inspection beside the native custom-format dump used for restoration.
Source metadata and the recovery inventory are separate JSON files. Application
files are grouped under `specifications/`, `boundaries/`, `deliveries/`,
`artifacts/` and `publications/`, with their original storage identities retained
in the manifest. The native dump itself contains both schema and data; separate
schema SQL does not need to be applied before restoring that dump.

```text
manifest.json
records.json
database/
  data/database.dump
  schema/schema.sql
  metadata/source.json
  metadata/inventory.json
  metadata/database.json
  metadata/restore-policy.json
  metadata/globals.sql                 # when selected
configuration/
  deployment.json                     # when selected
  credentials/s3/<credential-id>.json  # when selected and available
  credentials/worker.token            # when present and selected
  credentials/postgresql/<TLS-file>    # when referenced and selected
specifications/<storage-root>/...
boundaries/...
deliveries/incoming/...
artifacts/work/...
publications/submissions/...
```

Stored user passwords are password hashes, and issued API tokens are credential
digests. Export cannot reconstruct plaintext passwords or raw tokens that the
application never retained. Selected deployment settings, S3 credential files,
worker token and PostgreSQL TLS private keys can contain real secrets.
PostgreSQL globals can contain role-password verifiers.
Keep the entire ZIP in protected encrypted storage; the application does not
encrypt it. Server package directories use `0700`, files use `0600`, and downloads
require administrator access over the deployment's HTTPS ingress.

PostgreSQL globals and deployment credentials are preserved for reviewed manual
recovery. Import does not execute cluster SQL, change deployment settings, replace
credential files or select source specification/boundary activation pointers.
When configuration is selected, its deployment JSON preserves original
specification state-file bytes as base64 and known boundary link targets as
inert text. It never follows those links or activates their destinations.
This prevents a source installation from reconfiguring the destination merely
because its backup was uploaded. Files outside the supported managed roots,
remote objects, worker scratch, partial uploads, logs and private maintenance or
transfer journals need their own backup procedures.

## Capacity and retention

The review shows **Estimated ZIP size** and **Free backup storage**. Expand
**Storage requirements and limits** for original file bytes, measured compressed
file bytes, estimated database/package size, required free space, reserve and
configured limits. QC Tool measures lossless file compression while checking the
original file hashes, using bounded chunks. Files are compressed when this saves
space and stays within the importer's expansion limits; otherwise their original
bytes are stored directly. Compression never removes selected files or changes
their contents.

Native capture streams the already compressed custom database archive directly
into the ZIP instead of retaining a second complete dump beside it. Its size is
estimated from PostgreSQL storage, so the final ZIP size can differ. Execution
checks actual output bytes and the free-space reserve throughout creation.
Reloading the page does not interrupt the background export.

If capacity blocks export, deselect large file sections and retain a coordinated
independent storage backup, release older completed export packages after
verifying their independent copies, or provision more backup storage. Increasing
a limit cannot create free disk space. A package without file sections still
requires space for the complete database archive.

Import needs space for the uploaded ZIP and the files at their original,
uncompressed sizes, plus the configured reserve. PostgreSQL also needs capacity
for the separate restored database, indexes and transaction work. A small
compressed ZIP does not imply a small restored installation. QC Tool never
silently omits selected sections or deletes older backups to make a new one fit.

After verifying an independent copy, open **Create backup → Prepared backups** and choose **Delete**
for the file. Confirm the copy and choose **Delete saved ZIP**. This removes the
server download while preserving completed status, checksum and audit history. Imported packages,
restore journals and retained database files follow their separate recovery and
retention procedures.

## Import

1. Choose **Maintenance → Restore from ZIP**. Select a QC Tool package from an
   administrator you trust, then **Upload and review**. QC Tool identifies its
   type, including account or additive-record packages exported by earlier
   versions. New packages contain the full database. Under **Include the
   package's files?**, choose **Include packaged files** to restore verified
   packaged bytes, or **Skip packaged files** to import database contents
   without copying package files. A full database restore still includes all
   database records in either mode. Uploading never imports records or restores
   a database.
2. Turn on maintenance and wait for **Maintenance is on**, then return to the
   package. A records package uploaded before maintenance offers **Review import**.
   A database backup offers **Create restore database**. Follow the workflow for
   the identified package type.

For packages too large for a reliable browser upload, an operator can place the
package on private mounted server storage and stage it through the command line:

```sh
python3 -m qc_tool.frontend.manage data_transfer stage-file /private/backups/package.zip \
  --actor administrator --records-only
```

Use the actual administrator username and a path inside the frontend container.
The command validates and stages the package; it does not apply records or switch
databases. Open its operation in Admin to review and confirm the destination.
Omit `--records-only` only when the package's included files should be restored.
This avoids browser and proxy upload buffering; package limits and storage checks
still apply.

### Complete PostgreSQL database

Choose **Create restore database**. QC Tool allocates a unique empty database
for this import on the configured PostgreSQL cluster. You do not enter SQL or an
arbitrary destination name. The configured database identity needs permission
to create databases; if the deployment does not allow it, an operator can supply
a separately provisioned empty target through `QC_TOOL_RESTORE_DATABASE`.
Existing databases are never dropped, reset or overwritten.

Review the displayed destination, acknowledge the trusted source and choose
**Restore database**. The action is bound to that destination; no name entry is
required. Source archive, client and
target must have compatible supported versions; native operations require the
client/server major to match. Restore
uses one transaction with `--no-owner`, `--no-privileges` and `--no-tablespaces`:
row data is preserved while deployment ownership, database ACLs and tablespace
placement are intentionally remapped to the target environment. Database records
for QC Tool roles, grants and account privileges are still preserved.

There is no account mapping or selective merge for this profile. Only restore
packages from a trusted administrator: PostgreSQL schema restoration executes
the archive's SQL. Raw SQL scripts and arbitrary database dumps are not accepted
as QC Tool export ZIPs.

If files were selected, QC Tool verifies them and adds them to the configured
managed storage without overwriting existing files. An identical verified file
can be reused. A conflicting file requires review; it is never silently replaced.
Restored specification bytes and legacy boundary trees are retained in immutable
version/generation storage without selecting source activation pointers. New QC
work still needs locally configured specifications and an active boundary generation.
The restore has an operation journal for file recovery as well as the separate
database. Keep maintenance on if restoration or file publication needs recovery.
Database transactions do not make filesystem operations atomic.
Files used by a restored database remain protected in Storage even while that
database is inactive. Restore pins are retained; retiring a database and releasing
its storage requires a separate reviewed procedure, not deletion of its journal.

Restoration leaves the active database selected. When it completes, choose
**Review database switch**. This explicit review checks
the restored copy, current schema, connected records, available local files and
administrator access. If your account is not an administrator with the same
credentials in the copy, supply an active target administrator's credentials.
Acknowledge the storage/credentials review and choose **Use this database**.
QC Tool checks the displayed destination against the reviewed copy automatically.
Maintenance stays on and the previous
database remains intact.

Missing historical files remain visible warnings and do not invalidate a matching
database schema. Downloads and new QC actions still require their own verified
inputs. File availability is included in the switch review and its fingerprint.

Your maintenance administrator session stays bound to its original database
during this review window, so a different account ID in the restored copy cannot
lock you out of the controls or impersonate another administrator. Before
importing selective records into a switched database, sign in with an
administrator identity valid on that active database; import receipts belong to
that identity.

Verify the result while changes are paused. Under **Database recovery**, expand
the current database and **Switch back to …** for the previous database during the same maintenance
window. Once QC Tool has resumed, quick recovery expires because new work may
have been written. Use **Manage databases → Review switch** for a fresh reviewed
selection of a supported retained copy. Restoring an older schema does not
upgrade it; an incompatible copy cannot be activated. Do not run `database apply`
before a full archive restore or add missing tables to retained databases. See
the [native restore runbook](../../src/qc_tool/database/MANUAL_RESTORE.md).

### User profiles

Review the counts and each user's **Profile comparison**. Select an available
action for every user:

| Action | Effect |
| --- | --- |
| Import as a new inactive user | Creates an inactive account with an unusable password; review access locally before activation |
| Use an existing account | Leaves that account unchanged |
| Update profile | Updates only first name, last name and email on the explicitly matched existing username |
| Skip | Does not import that user |

Existing-account actions require a compatible explicit target. Matching names
or email addresses alone do not authorize an update. The review shows the
incoming first name, last name and email alongside the chosen existing profile.
Updating a profile preserves its ID, username, join date, password, activation,
roles, permissions, product grants, tokens, sessions and connected history.
Users not included in the package remain unchanged.

Choose **Save choices and review**, check the updated counts, then confirm the
destination and select **Import selected users**. Page controls save the current
page before moving; saved decisions on other pages remain. At least one user
must remain selected. After completion, review the created, reused, updated and
skipped counts before enabling any new accounts.

### Connected QC records

1. Review the additions and **Match imported users**. Existing usernames need an
   explicit mapping; matching names or email addresses do not approve one automatically.
   Each affected account shows its reason when a mapping is blocked. These mappings
   establish ownership of connected QC records; profile-update and skip-user
   choices belong to a separate **Users** import.
2. Review **New**, **Already present**, **Skipped** and
   **Needs a decision** counts.
   Open each conflict's differences. Use the existing compatible record without
   changing it, or skip the incoming record and its displayed dependent history.
   Incompatible job/review identities cannot replace an existing record.
3. If matches or decisions need changes, use **Save choices and review** to save
   them together. The updated review must be confirmed before importing. On
   multi-page lists, page controls save the current choices before moving and
   preserve decisions on other pages. Refreshing the review preserves saved choices.
4. Check **Original delivery ZIPs**. **Already on server — verified** means the
   retained file matches and will be reused. When importing files, a different
   destination file is preserved and blocks that incoming branch until you
   exclude it. Records-only imports leave differing bytes untouched and report
   their availability separately. Missing historical input checksums are
   shown explicitly; the tool cannot prove which file an old run checked without
   that evidence.
5. Type the displayed destination name, confirm the review and choose **Add records**.
   Progress updates automatically.

A portable QC dataset adds records to the **current database**, including one
that already contains QC history. Integer IDs are translated and connected
records remain linked. Existing accounts must be explicitly mapped. Application mappings
require matching usernames because retained upload paths use those names.
QC-record imports never overwrite an existing QC record or change an existing
account's profile, credentials or permissions. New accounts are inactive, have unusable
passwords and require local access review before activation.

Missing database dependencies, conflicting destination files selected for
copying, damaged included payloads, unsupported contracts or a changed
destination block import. Resolve
the displayed issue and use **Package source, checksums and technical details → Refresh review** before
continuing. Absent file bytes are different: their references remain in the
records, with missing/unverified availability shown explicitly. Remote S3
objects and credentials must be provisioned separately. Included original
specifications and immutable artifacts are verified and preserved unchanged.

Records-only imports can add a valid connected record graph while canonical
files are absent or differ; no file is modified in that mode. Missing,
unverified, differing, remote or unknown availability is retained in the import
receipt and subsequent exports. A retained ZIP is usable for a historical job
only when its bytes match that job's existing input checksum. Historical jobs
without trustworthy input hashes remain unavailable rather than gaining an
invented match. There is no arbitrary legacy-file adoption or attachment wizard
in this release; matching a ZIP by name alone is insufficient.

Approval, QC results and file availability are separate. Importing an uploaded,
failed, rejected or approved delivery does not approve it, rerun QC or change
its historical result. A missing input does not erase a recorded job; a matching
filename without trustworthy byte identity does not prove it is that job's input.

After completion, open one of the destination job links and choose **Delivery
file** in **Run details**. The download checks that job's original SHA-256,
preferring its immutable published input or using a matching retained owner upload. It returns
unavailable rather than serving a different file with the same name. A deleted
upload can still have a retained published original. Do not rename server folders
or edit database IDs to repair a link.

Supported portable packages carry stable provenance, so a later import can reuse
records already imported. Source review decisions are never forced over existing
accepted submissions. QC definition/boundary activation and account access remain
local administrator decisions. Unsupported schema contracts are blocked rather
than silently converted; see the [architecture and limits](../architecture/additive-record-import.md).

## Completion and interrupted transfers

Maintenance stays on after a transfer. Review the result and any required local
account or storage setup, then use **Turn off maintenance** on the maintenance page.
Interrupted QC jobs must be submitted again.

Each export or import page reopens its own tasks. While a transfer is running, its status
updates automatically and competing actions are blocked. Closing the browser
does not stop its runner. Files are copied and checksummed in bounded chunks;
PostgreSQL streams its dump directly into the ZIP. Only one transfer executes
at a time, without loading the whole database or its files into application memory.

A server/container restart or a stopped transfer process can interrupt creation.
Its saved journal and maintenance ownership remain available. Return to its
operation and use **Recover transfer** when offered; this is separate from
reloading a page. An unfinished export may need to create the ZIP again after
recovery. Completed ZIPs survive restarts when transfer storage is on the
deployment's persistent volume. Keep maintenance enabled if recovery is required.

A stopped runner offers recovery when its execution lock is free. Recovery checks
the destination and operation journal before doing anything again; portable
imports also reconcile their SQL receipt and file journal. A completed result that still holds maintenance
offers cleanup recovery. Active runners do not offer recovery.

A surviving native PostgreSQL tool retains the execution lease after its runner
dies, so another transfer or cancellation stays blocked until that child exits.

An uploaded file that has not been imported can be discarded. Cancellation is
available only when no import has committed and file state is safe. If recovery
cannot establish consistency, keep the journal and files and ask an operator to
inspect them. Do not remove the maintenance pin or edit state files to resume.
Discard removes the private uploaded or partial package after verifying that
cancellation is safe. Audit journals and completed packages are retained.

Operator commands use the same service:

```sh
python3 -m qc_tool.frontend.manage data_transfer status <operation-uuid>
python3 -m qc_tool.frontend.manage data_transfer run <operation-uuid>
python3 -m qc_tool.frontend.manage data_transfer retry <operation-uuid>
python3 -m qc_tool.frontend.manage data_transfer cancel <operation-uuid>
```

Use the normal deployment configuration and shared private storage paths.

Older export links open the unified complete-database package builder. Saved
operation links continue to open their own package and workflow.

## Database compatibility

Complete PostgreSQL packages preserve database schema and rows, together with
the explicitly selected extra sections. Older portable ZIPs transfer their
supported application graph and retained files. Missing files, remote objects,
unsupported external secrets and PostgreSQL physical recovery still require
the deployment's independent backup procedures.

The portable reader checks the package format, an explicit semantic record
contract and source metadata. A matching release label alone does not establish
compatibility. A structurally valid package with an unsupported contract can be
retained for review: the page shows source/target releases and bounded model or
field differences, blocks applying it and offers **Download original package**.
Damaged payloads and malformed packages are rejected. No fields are silently
dropped or converted. Only implemented, reviewed contract readers are supported;
this does not promise compatibility with future releases. Imports never migrate,
initialize, reset or repair an occupied database.

Every visit to **Admin → Database** checks the current database schema without
changing it. **Database health** shows **Schema matches** or the concrete
drift/availability issue and the check time. Expand **What does this check do?**
for the schema policy and expected contract version. **Check database schema**
repeats the check; it does not apply a schema change or start a background repair.
Other pages do not run this landing-page check.

Portable operations require a current matching source/destination schema. The
panel reports concrete mismatches; the optional operator command
`python3 -m qc_tool.frontend.manage database check` inspects them as well. A native backup remains
available for an older source schema. Native import uses its fresh prepared
destination and does not repair an occupied schema. Previously
completed downloads and safe staged-package discard remain available.

The [v3.0.0 database policy](../../src/qc_tool/database/README.md) remains
models-only. Use a fresh current-model target where required; this UI does not
introduce migration history or a baseline. Isolate external SQL/filesystem
writers before transferring or maintaining a deployment.

See [maintenance operations](../deployment/maintenance.md) and
[record-transfer architecture](../architecture/record-transfer-design.md).
