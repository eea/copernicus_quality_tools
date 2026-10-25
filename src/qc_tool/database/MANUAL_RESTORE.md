# Restore a native PostgreSQL copy

The Admin panel's complete PostgreSQL export contains a manifest and
`archive.dump`, preserving database schema and rows, including stored password
hashes, API credential digests, sessions and unmanaged database fields/tables.
It is distinct from portable account/application packages, which intentionally
exclude credentials. A native snapshot of an older draft schema preserves that
schema; it does not convert it into today's models.

Legacy conversion for v3.0.0 remains manual work outside this codebase. A prepared
handoff archive must contain the **new schema and converted records**, checksum,
source provenance and validation evidence. Restoration needs standard PostgreSQL
tools and the application; it needs no converter or application migration history.

Use an entirely new empty target. Keep the legacy database and existing local
databases intact. Do not run `database apply` before restoring an archive that
already includes schema. Do not use `--clean`, restore old legacy DDL over v3,
fake migration records or change traffic while preparing the copy.

## Restore through Admin

Choose **Prepare fresh destination** to allocate an empty database for this
operation on the configured PostgreSQL cluster. No SQL or arbitrary target name
is entered in the browser. The configured identity needs database-creation
permission. An operator may instead provision a separate empty database and set
`QC_TOOL_RESTORE_DATABASE` as an optional fallback. Existing application or
foreign objects block native restore even when their tables contain no rows.
Restoration never resets or drops existing databases, including the serving database.

With maintenance ready, upload a complete QC Tool export ZIP, review the displayed
destination, acknowledge the trusted source and choose **Restore database**. The
action is bound to that destination without requiring name entry. Restore runs
in a single transaction with
`--no-owner --no-privileges --no-tablespaces`: all row data remains present, while
objects belong to the deployment's restore identity and database ACLs/tablespace
placement are provisioned independently. QC Tool role and account permission
records remain database row data and are preserved.

Restoration leaves the active database selected. A separate **Switch active
database** action verifies schema/data/files and administrator access before
updating the private deployment-bound selection pointer. Review the displayed
destination and acknowledge external storage/credential compatibility; provide
target administrator credentials if the current account's credentials do not
match. Maintenance stays
on. Verify the selected copy before **Resume QC Tool** and sign in normally
after reopening. The previous database is retained. **Switch back** is available
only within that same uninterrupted maintenance generation; it is refused after
reopening because new work may exist. A schema-incompatible copy cannot be
activated; do not add tables or run an automatic repair to make it pass.

**Database copies** lists the active database, the configured original and
restore copies separately from saved backup ZIPs. After reopening, choosing a
previously used database is a new reviewed selection, not quick recovery.
QC Tool checks the selected copy's current schema, every SQL value, linked
records/files and administrator access, binds that review to its retained
physical identity, and requires a fresh confirmation in ready maintenance.
The databases stay separate; selection does not merge their changes or copy
additional files. A new restore's first selection must still exactly match its
original archive. After an explicitly approved first selection, its durable
private identity record permits later review of current contents without
requiring the old ZIP. Keep the shared private transfer directory with the
installation; missing, changed or foreign identity evidence is refused.

To free space, distinguish saved ZIPs from PostgreSQL copies. **Database copies**
shows current database sizes and read-only schema/table details. Its explicit
delete control is limited to unused restore destinations whose original private
ownership journal and PostgreSQL OID/owner/comment still match. Choose **Delete**
on the copy to remove it; no name entry or checkbox is required. Ready maintenance,
the current selection revision and a request bound to the exact copy are required.
The active database, configured original and previous recovery database remain
protected. A source copy is retained while other present restore copies depend
on its original identity; remove unused dependent copies first. Connected clients
or prepared transactions block deletion; QC Tool
never forces them off. Deleting a copy keeps the transfer audit, saved ZIP and
shared files. A deletion interrupted after PostgreSQL commits can be completed
from the same page without deleting another database. Use **Backup files** to
remove saved export ZIPs separately; their removal does not remove any database.

The manual commands below remain available for a separately reviewed operator
handoff or a deployment that does not use the Admin switch.

## Restore and verify

Use a PostgreSQL service entry or another operator-managed connection setting
for credentials. The example service must point to the **new empty database**;
replace its identity deliberately. Use compatible PostgreSQL client/server
versions and review the source archive's validation manifest. Native Admin
operations require matching client/server major versions; the frontend packages
client 14 for the current PostgreSQL 14 deployment. Upgrade that contract through
a reviewed change when changing server major versions.

```sh
# Run in the private handoff directory.
shasum -a 256 -c SHA256SUMS
pg_restore --list qc_tool_v3.0.0_available_history.dump > archive-list.txt

# Create a new database using the operator's maintenance service.
createdb --maintenance-db='service=qc_target_maintenance' qc_tool_v3_new
# Configure qc_v3_empty_target to point at qc_tool_v3_new before continuing.
pg_restore --dbname='service=qc_v3_empty_target' \
  --single-transaction --exit-on-error --no-owner --no-privileges \
  --no-tablespaces qc_tool_v3.0.0_available_history.dump
```

Set QC Tool's normal production environment to that new database, then run:

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage database check
```

The check is read-only. Reconcile counts, retained IDs/ownership/timestamps,
foreign keys and sequences against the handoff manifest. Verify that submitted
historical filenames still block a new upload, including case changes and
history belonging to deleted records or other users.

If restoration fails, preserve the archive/logs and allocate another empty
target after diagnosis. Do not clear an occupied database to retry.

## Complete the installation

Native backups preserve the stored account hashes and API credential digests;
they do not recover plaintext passwords or raw issued tokens. Preserve the
original `DJANGO_SECRET_KEY` and other required external secrets securely when
needed for restored sessions and application access. For historical handoffs
whose manifest records absent password hashes, use Django's `changepassword`
command to provision authorized accounts. Review active accounts, roles,
product grants and catalog specifications before exposing the restored copy.
Upload original specification bytes without rewriting them.

Provision private storage credentials and restore incoming ZIPs, detailed QC
reports, publication folders, specification version/state files and boundaries
from separate available backups. SQL metadata does not recreate these files.
Historical submission dates preserve duplicate protection; they do not prove
publication integrity or create approvals/receipts.

A single-database dump excludes PostgreSQL cluster identities and tablespaces.
Provision ownership, connection privileges and storage locations separately.
Only restore archives from a trusted administrator: PostgreSQL restoration
executes source schema SQL. QC Tool's ZIP validation/checksums do not establish
sender authenticity. Restrict package directories to `0700` and files to `0600`,
use HTTPS for UI downloads, and keep downloaded copies in encrypted external
storage. These ZIPs are not themselves encrypted.

Verify accounts, permitted and denied access, uploads, worker execution and
publication with the exact frontend/worker image pair. Historical stored QC
statuses do not establish same-input current-production parity. Keep the
production cutover and its recovery window in an operator installation record.
