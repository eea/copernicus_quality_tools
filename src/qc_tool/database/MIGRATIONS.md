# Database initialization for v3.0.0

This filename remains the database workflow entry point. **There are no
application migrations in v3.0.0.** Current models create a fresh schema;
existing schemas are checked without modification. Future migration management
starts with a separately reviewed 3.0.1-or-later change.

## Choose the operation

| Target | Operation |
| --- | --- |
| Entirely empty new database | `database plan`, then explicit `database apply`, then `database check` |
| Existing database matching current models | `database check`; `apply` also returns without writing |
| Partial, legacy or outdated schema | Stop. Use a separate fresh target; this version does not transform it. |
| Prepared v3 PostgreSQL archive | Restore into a new empty target using [MANUAL_RESTORE.md](MANUAL_RESTORE.md), then `database check` |
| Development model change | Change models directly and verify fresh disposable SQLite and PostgreSQL databases |

Use the exact source/image intended for the target and its normal environment
settings. Commands cover accounts, catalog, deliveries, publication and Django
framework tables together. They do not populate products or create demo users.

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage database plan
PYTHONPATH=src python3 -m qc_tool.frontend.manage database apply --traceback
PYTHONPATH=src python3 -m qc_tool.frontend.manage database check
```

`plan` and `check` perform read-only inspection. `apply` serializes PostgreSQL
initialization with an advisory lock, rechecks emptiness, creates current models
and bootstraps permissions/roles only in an empty schema. It never adds missing
tables or permissions to an occupied database. A complete matching schema is a
read-only no-op; any incompatible schema fails without reset or repair.

Readiness inspection covers managed tables (including automatic join tables),
columns and supported backend types, nullability, primary/foreign keys, required
uniqueness and declared constraints/indexes. This verifies the schema contract;
it does not certify account access, storage availability, restored record
completeness or QC acceptance parity. See [SCHEMA.md](SCHEMA.md).

CHECK-body comparison covers named `Meta.constraints` and SQLite JSON validity.
The inspector does not exhaustively compare field-generated positive-integer
checks, additional same-table constraints, triggers or privileges. Use the
archive's separate schema/data reconciliation evidence during manual handoff.
Only detected incompatibilities are refused; this is not a general SQL adoption
or repair mechanism.

## Startup

Production startup runs `database check` and refuses an unready database. Run an
explicit initialization job only for a confirmed empty installation, or manually
restore a prepared archive. Do not point either operation at legacy production.

The startup adapter adds `--allow-maintenance-recovery` to `database check`.
This option is restricted to `check --database default`; ordinary checks stay
strict. It can admit the maintenance UI after an unavailable explicit selection
only when the same maintenance generation is still ready, the retained source
has recorded verification evidence and its identity/schema/administrator access
pass read-only inspection. It never initializes, repairs, switches or resumes a
database. Recovery startup skips demo bootstrap and local initialization. An
unselected incompatible database remains refused.

Development/test startup can opt into `QC_TOOL_INITIALIZE_ON_STARTUP=yes`.
It uses the same guarded initializer. Automatic initialization is refused in
production. The former migration-startup option is no longer supported.
CI and startup never generate migration definitions.

## Local verification

Use a fresh isolated test database, with no production storage or network access.
The schema check refuses nonempty targets; its synthetic fixtures and checks
are test-only. The frontend test suite creates its own disposable test database.

```sh
PYTHONPATH=src python3 -m unittest qc_tool.database.tests.test_source
PYTHONPATH=src python3 -m qc_tool.database.checks.source
PYTHONPATH=src python3 -m qc_tool.database.checks.schema
PYTHONPATH=src python3 -m qc_tool.frontend.manage test qc_tool.database.tests.integration
```

Repeat schema and integration verification on SQLite and PostgreSQL. Include
fresh initialization, read-only repeated application, production-mode readiness,
refusal of partial/foreign schemas, authorization/bootstrap and retained history
lookups. Check the [testing guide](../../../docs/development/testing.md) for the
supported container runtime. Do not generate migrations as a verification step.

## Manual legacy conversion and restore

Conversion scripts are not part of QC Tool. Preserve the original exports and
private conversion evidence separately, validate the transformed records in a
new target, then hand off a native PostgreSQL archive, checksum, provenance and
restore report. The archive can be restored without converter code. Available
historical exports are not a coherent current production snapshot.

Follow [MANUAL_RESTORE.md](MANUAL_RESTORE.md) for the standard restore procedure.
User passwords, product grants/catalog, private credentials and shared files need
separate evidence; SQL cannot reconstruct absent ZIPs or published reports.
Historical submission dates block duplicate filename admission without inventing
modern publication receipts or approvals.

## Failure and recovery

A failed check blocks startup. Inspect the target and retain its data. No failure
justifies automatic reset, fake records or schema repair. If initialization fails
on a newly allocated disposable target, diagnose it and use another empty target;
do not repurpose an existing database. If a restore fails, retain its logs and
retry into another new empty target after fixing the cause.

Production cutover is a later manual operator action. Coordinate source writes,
verify a final backup and a recovery copy, provision accounts/storage/catalog,
validate the exact image pair, and switch traffic only after those checks pass.
Record the installation using [RELEASE_TEMPLATE.md](RELEASE_TEMPLATE.md).
