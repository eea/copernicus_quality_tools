# Import the legacy QC Tool dump

`import_legacy_dump` converts the old QC Tool PostgreSQL dump into the current
schema. It reads text `COPY` records without executing the dump's SQL. The default
is a dry run: it validates the source and prints an aggregate JSON report without
connecting to the target database.

The converter supports the schema in
`backups/20260907/qc_tool_production_20260907.sql`. It is a separate data-import
operation, not a schema migration or a restore over an existing database.

## What can be recovered from this backup

| Source information | Result |
| --- | --- |
| 97 users | IDs, usernames, password hashes, names, email, flags and account dates retained |
| 52 user profiles | Retained; 45 users without profiles receive blank profiles |
| 57,583 deliveries | IDs, owners, original filenames, sizes, dates, product identifiers, descriptions and deletion flags retained |
| 15,992 submitted deliveries | Original submission dates retained as historical records |
| 61,319 QC jobs | UUIDs, delivery relationships, states, dates, descriptions, reported units and execution settings retained |
| 29,688 S3 locations | Hosts, buckets and object prefixes retained; credentials left blank |
| 196 administration events | Actors, dates, text and original object IDs retained; links retained only where their target IDs are preserved |
| Old groups and memberships | Unrecognized groups retained under `legacy:` names, without active permissions |
| Direct user permissions | Resolved by app label, model and codename; unavailable permissions counted in the applied report |

Duplicate filenames are legitimate historical rows and are **not deduplicated**.
The 21,144 deleted delivery records remain deleted. Reported `aoi_code` values
use the existing legacy adapter for `product_unit_code`; verified unit fields
stay empty. Timestamps respect the target application's timezone configuration.
Any legacy waiting/running jobs become `worker lost`, preventing accidental
execution after import.

The ZIPs, QC reports and submitted-delivery folders are unavailable. The SQL dump
cannot recreate them, content hashes, verified submission receipts, approvals,
release snapshots or authoritative product units. Historical submission dates
do **not** create entries eligible for the current approval workflow or make any
product completed. Historical QC states are retained, but detailed results and
downloads cannot be restored from this backup.

No products are created and no specifications are modified. Administrators must
upload the original specification JSONs through **Products → Upload specification**.
Old API credentials, sessions and migration history are not imported. S3
credentials require replacement before the stored locations can be used.

## 1. Validate and inspect the report

Run from the repository root in the normal frontend Python environment:

```bash
PYTHONPATH=src python3 -m qc_tool.frontend.manage import_legacy_dump \
  src/qc_tool/database/backups/20260907/qc_tool_production_20260907.sql \
  --report /tmp/qc-legacy-dry-run.json
```

`--dry-run` is optional. The report contains counts, source SHA-256 and warnings,
not account details or credentials. Report files are created with mode `0600`;
existing files are never overwritten. Keep the source dump private and unchanged:
it remains the record of information that cannot map to the new schema. Local
database backups are excluded from Git.

## 2. Review user access

Every imported user receives `default`; existing superusers also receive `admin`.
Active state and password hashes are preserved. Supported legacy hashes continue
to work; unsupported hash algorithms are counted and require a password reset.
Legacy staff flags remain intact. Staff-only users do not automatically become
product managers or administrators.

Names such as `country_manager` and `product_admin`, profile countries/families,
and previous uploads do not establish current product permissions. Assign these
through administration after importing, or supply a reviewed JSON access map:

```json
{
  "users": {
    "47": {
      "roles": ["product_manager"],
      "products": ["clms_ua_lcuc_c2021-2024_v010ha"],
      "regions": []
    },
    "48": {
      "products": ["clms_ua_lcuc_c2021-2024_v010ha"]
    }
  }
}
```

Keys are **source user IDs**; these example IDs must be replaced with reviewed
IDs from your backup. Roles are additive to the preserved roles and baseline
`default` role. Valid roles are `default`, `product_manager`, and `admin`.
Products must use their canonical identifiers. Region codes are optional and
must match your application's geographic scope; omitting them grants no regions.
Regional visibility also requires the corresponding account capabilities; a
region scope alone does not reproduce the old `country_manager` role.
An explicit grant does not create a product. Its specification must still be
uploaded before the catalog can expose it.

Pass the same `--access-map /private/path/access-map.json` to both the dry run
and actual import. Without a map, no product or region assignments are inferred.
Review access before allowing users onto the new deployment.

## 3. Rehearse in a fresh disposable database

While `policy.json` is `draft`, only development/test rehearsal is supported.
The command rejects production imports until the release is explicitly frozen.
The following SQLite example leaves all existing databases alone. The temporary
directory must be new, and the schema is built through the whole-app command:

```bash
QC_LEGACY_REHEARSAL_DIR="$(mktemp -d /tmp/qc-legacy-rehearsal.XXXXXX)"
(
  set -eu
  export PYTHONPATH=src QC_TOOL_ENVIRONMENT=test DB_ENGINE=sqlite
  export FRONTEND_DB_PATH="$QC_LEGACY_REHEARSAL_DIR/target.sqlite3"
  export WORK_DIR="$QC_LEGACY_REHEARSAL_DIR/work"
  export INCOMING_DIR="$QC_LEGACY_REHEARSAL_DIR/incoming"
  export BOUNDARY_DIR="$QC_LEGACY_REHEARSAL_DIR/boundaries"

  python3 -m qc_tool.frontend.manage database apply
  python3 -m qc_tool.frontend.manage import_legacy_dump \
    src/qc_tool/database/backups/20260907/qc_tool_production_20260907.sql \
    --apply --target-database "$FRONTEND_DB_PATH" \
    --report "$QC_LEGACY_REHEARSAL_DIR/import-report.json"
  python3 -m qc_tool.frontend.manage database check
)
```

The imported database contains personal information and password hashes. Retain
it only as needed for the rehearsal, under the same controls as the source.

For PostgreSQL, configure a **separate fresh target** using `DB_ENGINE=postgres`
and the target's `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`
and `POSTGRES_PASSWORD`. Initialize it with `database apply`, then use
`--apply --target-database "$POSTGRES_DB"`. The name must exactly match the
configured target. `--database` optionally selects a configured Django alias;
initialize and check that same alias as well.

Keep the target offline during import. The converter accepts only empty business
tables plus the standard permission/content-type/role bootstrap. Even a single
existing user causes refusal. All writes use one transaction, foreign keys are
preserved, and sequences are repaired. PostgreSQL tables are locked during the
freshness check and writes; acquiring those locks times out after five seconds.
Source validation happens before any writes. A failed import rolls back its
records. A successful import cannot be rerun or merged into an occupied target;
use another fresh disposable target for another rehearsal.

## 4. Production cutover after release freeze

Follow the [one-time cutover](MIGRATIONS.md#one-time-manual-production-cutover)
using the frozen release and a new, initialized PostgreSQL database. Do not label
production as `test` to bypass the draft guard. Pin the code revision, access map
and source SHA-256 used in the successful rehearsal, and repeat the import there.
The source dump's migration recorder never replaces the target's own history.

Compare the applied report with the dry run, test login and product access,
review omitted permissions, and confirm the historical submission limitations.
Keep the source backup; missing files cannot be repaired by retrying the importer.
Changing live database configuration or switching traffic is a separate operator
step. This command does neither.

## Verification

Synthetic tests cover COPY decoding, account/access mapping, retained IDs and
timestamps, unavailable files, no invented catalog/approval state, safe reports,
empty-target enforcement, rollback and sequence repair. Run them on disposable
SQLite and PostgreSQL targets:

```bash
PYTHONPATH=src python3 -m qc_tool.frontend.manage test \
  qc_tool.database.tests.test_legacy_dump \
  qc_tool.database.tests.integration.test_legacy_accounts \
  qc_tool.database.tests.integration.test_legacy_import \
  qc_tool.database.tests.integration.test_legacy_audit_links \
  qc_tool.database.tests.integration.test_legacy_command --noinput
```

All 63 migration tests pass on SQLite and PostgreSQL. The actual 20260907 dump
has also been rehearsed on isolated PostgreSQL; every imported user, profile,
storage source, delivery and job field matched the prepared source conversion,
and all counts in the recovery table above reconciled. This does not perform or certify
a production cutover: repeat verification against the eventual frozen release.
