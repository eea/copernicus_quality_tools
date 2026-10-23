---
title: Import and export records
parent: User guide
nav_order: 5
---

# Import and export records

Open **Admin → User management** (`/admin/users/`) for **Import users** and
**Export users**. Open **Admin → Database** (`/admin/database/`) for **Import
records**, **Export records**, **Create full backup** or **Restore a backup**.
Only QC Tool administrators can use transfer controls. **Transfer history**
reopens previous work. The previous `?tab=transfers` chooser remains supported.

Record packages add information to an existing installation. Full PostgreSQL
backups preserve the database for recovery into a separate destination. They
have different review and confirmation steps.

## Export users or QC records

Choose **Export users** in **User management** to export **All account profiles** or
**Selected account profiles**. The searchable user picker appears for selected
profiles. These packages include profile information and source roles/product
grants for review; they exclude credentials, deliveries and QC history.

Choose **Export records** in **Database** for the supported connected
QC dataset. Its record scope is fixed: products, definitions, delivery plans,
deliveries, jobs, review history and required account profiles. This is the
maintained QC record graph, not an arbitrary selection of PostgreSQL tables.

Choose **Records only** to keep file identities and references without copying
their contents, or **Records and available files** to include available local
delivery ZIPs and connected artifacts. Submitted files do not need approval to
be preserved. Missing files are reported; they do not prevent exporting their
records. User-profile packages never include files.

1. Choose the relevant section and, for users, which profiles to include. For
   QC records, choose whether to include files.
2. If needed, follow **Turn on maintenance**. Wait for **Maintenance is on** and
   return to the export. The maintenance page checks progress automatically;
   enabling it interrupts submitted QC jobs.
3. Choose **Review users export** or **Review records export**, check the record
   counts and file availability, then create the export package. Changing the
   records or file choice requires another review.
4. Progress updates automatically. Download the file when the export is ready.

Portable profiles exclude passwords, API credentials, sessions and service
credentials. Their source roles and product grants are review information;
imports do not grant that access automatically.

The export review shows the total record count and portable-package limit
(250,000 by default). Product units and catalog records count too. If the
selection exceeds that limit, no records are dropped and no export starts.
**Review full database backup** opens the backup workflow with your file choice
preserved. A full backup restores into a separate database; it cannot append to
an existing one. If you need an additive package above the current limit, ask
the deployment operator to review frontend memory capacity and
`QC_TOOL_TRANSFER_MAX_RECORDS`. Byte-size and integrity limits still apply.

## Back up the complete database

Open **Database** and choose **Create full backup** for a complete
native PostgreSQL backup. This task always includes the full database; it has
no record-selection controls. Choose **Records only** for the database archive
alone, or **Records and available files** to include retained local storage.

1. Turn on maintenance and wait for QC work to stop.
2. Choose **Review database backup** and inspect the included information.
3. Choose **Create database backup**, then download it when preparation finishes.

The backup includes all database schema and rows: password hashes, API credential
digests, sessions, transfer receipts and fields/tables outside the portable
contract. Including files also preserves retained local delivery ZIPs, job and
publication artifacts, original specifications and boundary files in the
configured managed storage. It includes unlinked delivery ZIPs found there,
including files retained from an earlier database. This inventory does not scan
the whole server. Temporary work, logs and files outside the managed roots are
excluded. The review reports included file counts and exclusions.

The complete database ZIP contains a QC Tool manifest and PostgreSQL custom
archive (`archive.dump`). Its hashes verify the packaged bytes; they do not
authenticate the sender. Native backup does not require the source schema to
match today's Django models: an older draft database can be preserved without
altering or repairing it. The installed dump client and source server must have
the same PostgreSQL major version.

Native backup includes stored password hashes and API credential digests, not
recoverable plaintext passwords or previously issued raw API tokens. It also
preserves account activation, privileges and stored sessions exactly as database
rows. Handle the package as sensitive authentication data. Private server storage
uses directories `0700` and files `0600`; downloads require administrator access
and use non-cacheable responses. Deploy the application behind HTTPS. The ZIP
itself is not encrypted. Store downloaded backups in approved encrypted storage.

A single-database archive excludes PostgreSQL cluster roles/tablespaces. The
optional file inventory excludes remote S3 objects, private credential
directories and environment secrets. Back up those separately. Preserve
`DJANGO_SECRET_KEY` and required S3 credentials
securely when they are needed for restored sessions and application access.
Database rows cannot recreate absent uploads, boundaries or publication files.

## Import

1. Choose **Import users** in **User management** or **Import records** in
   **Database**. For a full PostgreSQL backup, choose **Database → Restore a
   backup**. Select a QC Tool package from an administrator you trust,
   then **Upload and review**. QC Tool identifies its type. If it belongs to
   another section, the page explains the change before continuing. For records
   and backups, choose **Records only** to skip copying package files, or
   **Records and available files** to restore verified packaged bytes as well.
   Uploading
   never imports records or restores a database.
2. Turn on maintenance and wait for **Maintenance is on**, then return to the
   package. A records package uploaded before maintenance offers **Review import**.
   A database backup offers **Create restore database**. Follow the workflow for
   the identified package type.

### Complete PostgreSQL database

Choose **Create restore database**. QC Tool allocates a unique empty database
for this import on the configured PostgreSQL cluster. You do not enter SQL or an
arbitrary destination name. The configured database identity needs permission
to create databases; if the deployment does not allow it, an operator can supply
a separately provisioned empty target through `QC_TOOL_RESTORE_DATABASE`.
Existing databases are never dropped, reset or overwritten.

Review the displayed destination, type its required confirmation, acknowledge
the trusted source and choose **Restore database**. Source archive, client and
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
Type the displayed database name, acknowledge the storage/credentials review
and choose **Switch active database**. Maintenance stays on and the previous
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

Verify the result while changes are paused. Under **Backups & recovery**, expand
**Database settings & rollback** and **Switch back to …** for the previous database during the same maintenance
window. Once QC Tool has resumed, switching back is blocked because new work may have been written;
use a new reviewed backup/restore instead. Restoring an older schema does not
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
the displayed issue and use **Package details → Refresh review** before
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

New portable exports carry stable provenance, so a later export/import can reuse
records already imported. Source review decisions are never forced over existing
accepted submissions. QC definition/boundary activation and account access remain
local administrator decisions. Unsupported schema contracts are blocked rather
than silently converted; see the [architecture and limits](../architecture/additive-record-import.md).

## Completion and interrupted transfers

Maintenance stays on after a transfer. Review the result and any required local
account or storage setup, then use **Turn off maintenance** on the maintenance page.
Interrupted QC jobs must be submitted again.

**Transfer history** reopens previous transfers. While a transfer is running, its status
updates automatically and competing actions are blocked. Closing the browser
does not stop its runner.

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

Older direct links with `?tab=export&scope=database` still open the full-backup
task. Saved operation links continue to open their own package and workflow.

## Database compatibility

Complete PostgreSQL packages preserve database schema and rows. Portable ZIPs
transfer the supported application graph and retained files. Neither profile
includes every external file or secret needed for disaster recovery.

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
changing it. **Schema & migrations** shows **Schema matches** or the concrete
drift/availability issue, the check time and expected contract version. **Check
database schema** repeats the check; it does not apply a schema change or start
a background repair. Other pages do not run this landing-page check.

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
