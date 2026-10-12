# Make a private legacy snapshot and rehearse the conversion locally

[`scripts/migration/legacy/rehearse.py`](../../../scripts/migration/legacy/rehearse.py)
automates the existing [legacy importer](LEGACY_IMPORT.md) in a new private
directory. It accepts a complete plain dump or the explicitly mixed interchange
described below, and defaults to a dry run. `--apply` creates a fresh, offline SQLite
database from the current models through the application-wide
`database plan|apply|check` workflow, then imports and reconciles the snapshot.
It never resets or merges into an existing database, starts services, connects
to production, generates migrations, or edits specifications.

This is a **local conversion rehearsal**, including when the repository policy
is `draft`. Production cutover remains the separate frozen-release operation
described in [MIGRATIONS.md](MIGRATIONS.md#one-time-manual-production-cutover).

## Obtain one coherent source snapshot

Django administrator credentials provide application access; they do not supply
PostgreSQL/SSH access or a complete database backup. Ordinary admin user pages do not
provide the password-hash records needed to preserve users' existing logins.
A table-by-table web export is not a coherent PostgreSQL snapshot.

Use the production host's PostgreSQL client, the database/container operator,
or a database-backed export endpoint explicitly provided by that deployment.
Run this command on a host with authorized database access. Replace the service
name and destination with the deployment's actual values:

```bash
umask 077
QC_SNAPSHOT_DIR="$(mktemp -d /secure/backups/qc-legacy-snapshot.XXXXXX)"
pg_dump --dbname='service=qc_production_readonly' \
  --format=plain --encoding=UTF8 --no-owner --no-privileges \
  --file="$QC_SNAPSHOT_DIR/production.sql"
```

The parent directory must already exist. Configure the PostgreSQL service
and a private `0600` password file outside the repository; do not place passwords
in the command, connection URI, chat, or exported shell environment. Local
peer authentication on the database host is another option. A successful
`pg_dump` is a consistent database snapshot while ordinary writers continue.
See the official [pg_dump documentation](https://www.postgresql.org/docs/current/app-pgdump.html).
Request the **complete database**: do not select individual tables, use
`--inserts`, export CSV, or generate a directory/custom archive. The converter
requires the plain dump's UTF-8 declaration, text `COPY` blocks, supported
legacy columns, and completion marker. It parses those records without executing
the dump's DDL or commands. Transfer `production.sql` privately to this machine.
PostgreSQL documents [connection service files](https://www.postgresql.org/docs/current/libpq-pgservice.html)
and [private password files](https://www.postgresql.org/docs/current/libpq-pgpass.html).

Database consistency does not establish consistency with the ZIP/report/shared
storage. Copy the referenced storage separately for a complete recovery backup.
A final production cutover additionally needs a coordinated write stop and a
final database/storage snapshot; that operation is outside this local wrapper.

## Audit, then import into a new local database

Run from the repository root in the frontend Python environment:

```bash
python3 -m scripts.migration.legacy.rehearse /private/path/production.sql \
  --output-dir /private/path/qc-legacy-audit-20261012

python3 -m scripts.migration.legacy.rehearse /private/path/production.sql \
  --apply --output-dir /private/path/qc-legacy-import-20261012
```

Each output directory **must not exist**. Omit `--output-dir` to create a new
private temporary directory. The wrapper copies the original source bytes into
`snapshot.sql`, calculates SHA-256 before and after copying, and checks both
the original and copied source again after the run. It does not rewrite the
source. A changed source or incompatible/truncated dump fails the run.

Use the same reviewed `--access-map /private/path/access-map.json` for both runs
when current product grants and manager roles have been reviewed. Its original
bytes are also copied privately and checked. Existing superuser/default roles,
account flags and supported password hashes are handled by the importer;
country/profile labels or uploads never infer current product-manager grants.

The child commands receive explicit local SQLite paths and fresh storage paths.
Inherited application/database credentials are not passed through. Child output
is suppressed because unexpected exceptions may contain source data; the wrapper
prints stage names, exit status, counts and SHA-256 only. Run this script in a
Python environment with the frontend dependencies installed; it does not install
packages or launch Docker automatically. It can also run inside a one-shot
frontend container with only the snapshot and new output directory mounted.

## Evidence and limits

The private run directory contains:

| Artifact | Meaning |
| --- | --- |
| `snapshot.sql` | Unchanged source bytes; contains personal information and possibly legacy credentials |
| `dry-run-report.json` | Planned counts, omissions, warnings and source checksum |
| `target.sqlite3` | New offline local database, only with `--apply`; contains users/password hashes/history |
| `applied-report.json` | Importer's committed counts, only after a successful import |
| `reconciliation-report.json` | Independent read-only aggregate checks, SQLite integrity/foreign keys, history/state counts and absent invented evidence |
| `rehearsal-manifest.json` | Stage exit codes, source/access-map checksums and final status; `passed` means the requested audit/rehearsal passed |

The run directory is `0700`; private files use `0600`. Keep it outside published
artifacts and Git, and retain it only under the same controls as the source
backup. A failed run remains available for inspection and is never retried into
its occupied target. Invoke the script with a new output directory to rehearse
again.

The conversion retains user and delivery/job identifiers, password hashes,
deletion flags and historical submission dates. Waiting/running legacy jobs are
disabled. The aggregate checks compare users, deliveries, jobs, storage sources,
admin logs, grants, submission dates, deletion flags and mapped job states. They
also check that no products, approved/verified submission receipts, live API
tokens, sessions, content hashes, ZIP-verified units or S3 credentials have been
invented. This is not a field-by-field comparison, login/access smoke test,
PostgreSQL performance rehearsal, or storage restoration.

Historical submission dates provide evidence for the current conflict/history
logic. They do not prove that two different filenames/archives are the same
delivery, and they do not become current approval records. Full duplicate
protection must be verified against the actual upload/submission rules and the
available original archives; a database import alone cannot establish their
content hashes. Detailed QC reports, ZIP downloads and submitted folders cannot
be reconstructed from SQL. See [LEGACY_IMPORT.md](LEGACY_IMPORT.md) for the exact
field mapping and omissions. Upload original product specification JSONs through
the supported administration flow, review current product grants, and test
allowed/denied access and representative duplicate submissions before any
production switch.

## When only web administration and older exports are available

[`scripts/migration/legacy/prepare_sources.py`](../../../scripts/migration/legacy/prepare_sources.py)
can prepare a separate, explicitly **mixed available-history copy** from an older
complete SQL snapshot, later complete delivery/job CSVs, and a current read-only
admin-user capture. This does not establish a coherent current production
snapshot. Keep the older raw snapshot and every newer source unchanged.

```bash
python3 -m scripts.migration.legacy.prepare_sources \
  --older-dump /private/path/older-production.sql \
  --deliveries-csv /private/path/dashboard_delivery.csv \
  --jobs-csv /private/path/dashboard_job.csv \
  --current-users-json /private/path/current-users.json \
  --output-dir /private/path/qc-mixed-history-prepared

python3 -m scripts.migration.legacy.rehearse \
  /private/path/qc-mixed-history-prepared/prepared-import.sql \
  --apply --output-dir /private/path/qc-mixed-history-import
```

Both output directories must be new. The preparation helper preserves private
byte-for-byte copies of all inputs and writes `source-preparation-manifest.json`
with hashes, source dates/URLs supplied in the capture, row counts, limitations
and the password/access policy. `prepared-import.sql` is generated COPY data for
the importer; its header and manifest explicitly distinguish it from a raw
database backup. The second command copies that interchange unchanged into its
own run directory, labels the run as mixed history, and retains a private copy
of the matching preparation manifest when present beside the interchange. Its
reconciliation independently confirms that every imported password is unusable.

The admin JSON contains `captured_at`, `source_url`, `limitations` and `users`.
Each user supplies the canonical `auth_user` fields: `id`, `username`, names,
email, active/staff/superuser flags, `date_joined` and nullable `last_login`.
Dates must include their UTC offset, or the user row must provide an explicit
IANA `source_timezone` such as `Europe/Prague`. The helper derives the correct
summer/winter offset for naive timestamps and records the number converted;
ambiguous or nonexistent clock-change times require an explicit offset instead.
The original capture bytes stay unchanged. Optional `source_groups` and
`source_user_permissions` lists remain archived as source evidence. The helper
**always replaces every password with an unusable value**, including if a
password field is present in the JSON. Explicitly provision/reset target users
before attempting login; neither older password hashes nor web-masked hash
fragments establish the current credential.

The CSV headers must exactly match the supported legacy columns, including IDs
and relationship fields. Empty cells in nullable columns become `NULL`.
Delivery/job tables replace the older versions; storage and admin history come
from the older dump. Missing user/storage/delivery references cause refusal;
the helper never invents records or clears those relationships. Older group
membership, direct-user permission, and group-permission links are cleared in
the generated interchange so current accounts cannot silently regain stale
access. Current superuser flags still establish `admin`, every user receives
`default`, and product/manager grants need the reviewed access map.

Use current web exports to compare the covered historical records and detect
newer activity. A lossy spreadsheet view is not overlaid onto canonical tables,
and the local copy does not claim to include jobs/storage that were unavailable
through the authorized web access. Keep its report labelled with those source
dates and completeness limits when evaluating duplicate-submission protection.
