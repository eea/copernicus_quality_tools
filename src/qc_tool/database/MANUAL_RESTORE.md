# Restore a prepared PostgreSQL copy

Legacy conversion for v3.0.0 is a manual task outside this codebase. The handoff
is a native PostgreSQL custom archive containing the **new schema and converted
records**, a SHA-256 checksum, source provenance and validation evidence.
Restoration needs standard PostgreSQL tools and the application; it needs no
legacy converter or application migration history.

Use an entirely new empty target. Keep the legacy database and existing local
databases intact. Do not run `database apply` before restoring an archive that
already includes schema. Do not use `--clean`, restore old legacy DDL over v3,
fake migration records or change traffic while preparing the copy.

## Restore and verify

Use a PostgreSQL service entry or another operator-managed connection setting
for credentials. The example service must point to the **new empty database**;
replace its identity deliberately. Use compatible PostgreSQL client/server
versions and review the source archive's validation manifest.

```sh
# Run in the private handoff directory.
shasum -a 256 -c SHA256SUMS
pg_restore --list qc_tool_v3.0.0_available_history.dump > archive-list.txt

# Create a new database using the operator's maintenance service.
createdb --maintenance-db='service=qc_target_maintenance' qc_tool_v3_new
# Configure qc_v3_empty_target to point at qc_tool_v3_new before continuing.
pg_restore --dbname='service=qc_v3_empty_target' \
  --no-owner --no-privileges --exit-on-error qc_tool_v3.0.0_available_history.dump
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

The supplied historical copy has evidence limits recorded in its private
manifest. In particular, web-admin export access does not supply usable password
hashes; use the standard Django `changepassword` command to provision authorized
accounts securely. Product grants and catalog specifications must be reviewed
explicitly. Upload the original specification bytes without rewriting them.

Provision private storage credentials and restore incoming ZIPs, detailed QC
reports, publication folders, specification version/state files and boundaries
from separate available backups. SQL metadata does not recreate these files.
Historical submission dates preserve duplicate protection; they do not prove
publication integrity or create approvals/receipts.

Verify accounts, permitted and denied access, uploads, worker execution and
publication with the exact frontend/worker image pair. Historical stored QC
statuses do not establish same-input current-production parity. Keep the
production cutover and its recovery window in an operator installation record.
