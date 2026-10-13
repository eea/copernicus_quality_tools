# QC Tool database lifecycle

This package owns QC Tool's schema policy, whole-application database command,
checks, legacy conversion and documentation.

**QC Tool 3.0.0 uses a models-only schema.** [policy.json](policy.json) declares
`draft` with an empty `baselines` mapping. Keep no first-party migration
definitions or schema snapshots in this version. The `draft` label selects the
schema workflow; it is independent of the application's release number.
Initial migration history may be introduced only in **3.0.1 or a later release**,
through a separately reviewed freeze and transition plan.

| Schema lifecycle | Workflow |
| --- | --- |
| 3.0.0, models-only (`draft`) | Change models directly; initialize fresh disposable targets from those models. No first-party migration definitions or baseline snapshots. |
| First migration-managed release, 3.0.1 or later | Review the transition, generate initial definitions, and change policy in the same release preparation. |
| After that explicit freeze (`released`) | Preserve established migration identities and add reviewed forward migrations with schema changes. |
| Legacy conversion | Import and reconcile supported source records into a separate fresh target; never restore legacy DDL over the application schema. |

Use `python3 -m qc_tool.frontend.manage database plan|apply|check`. Models-only
initialization creates missing tables and standard permissions/roles without
populating products. It does not upgrade existing tables, constraints or indexes,
and it never resets a database. Use a fresh disposable database after a model
schema change, even when an existing product catalog is empty.

New catalogs remain empty until an administrator uploads original product
specifications through **Products → Upload specification**, or an operator runs
a reviewed import. Specifications and uploaded snapshots are never rewritten.

The current production guard rejects models-only database commands in a secure
environment. Production initialization and cutover remain deferred; do not
circumvent that guard or generate a 3.0.0 baseline to bypass it. See the current
[release record](releases/3.0.0.md) and [runbook](MIGRATIONS.md).

## Start here

| Your task | Procedure |
| --- | --- |
| Review model ownership and retained data | [Application schema](SCHEMA.md), [table dictionary](TABLES.md) and [database audit](AUDIT.md) |
| Change the 3.0.0 models-only schema | [Models-only development](MIGRATIONS.md#draft-schema-development) |
| Verify a schema on a disposable database | [Local verification](MIGRATIONS.md#local-verification) |
| Transfer supported legacy records | [SQL dump importer](LEGACY_IMPORT.md) |
| Make a separate local history copy | [Local rehearsal and available web sources](LOCAL_LEGACY_REHEARSAL.md) |
| Plan the first migration-managed release, 3.0.1 or later | [Reviewed freeze](MIGRATIONS.md#freeze-the-first-release) and an explicit existing-database transition plan |
| Maintain history after that freeze | [Forward-migration development](MIGRATIONS.md#development-after-the-major-release-is-frozen) |
| Prepare artifacts and deployment evidence | [Release preparation](MIGRATIONS.md#prepare-a-release) and [release template](RELEASE_TEMPLATE.md) |
| Recover from a failed operation | [Failure and recovery](MIGRATIONS.md#failure-and-recovery) |

An existing model-created 3.0.0 database has no first-party applied migration
history. New initial migrations cannot automatically adopt its tables. Before
3.0.1 or later, review a fresh-target data conversion or another explicitly
approved adoption design with schema and data evidence. Framework identity types
and integrity definitions may differ between model initialization and a generated
migration graph even when application field names match. Verify the complete
schema, not just the QC Tool tables. A version bump, startup, `database check`,
or `--fake-initial` is not that transition. Do not reset, fake, or rewrite an
existing database or its recorder.

## Package layout

```text
src/qc_tool/database/
├── README.md                       # Policy and entry points
├── SCHEMA.md                       # Table ownership and persistence boundaries
├── TABLES.md                       # Fields, constraints and indexes
├── MIGRATIONS.md                   # Current initialization and future migration workflow
├── RELEASE_TEMPLATE.md             # Release decisions and evidence
├── policy.json                     # 3.0.0: draft, no baseline identities
├── policy.py                       # Policy and Django module selection
├── deployment.py                   # Whole-application command and locks
├── legacy/                         # Offline legacy record conversion
├── apps.py                         # Django command discovery
├── management/commands/            # database and import_legacy_dump
├── migrations/                     # Namespace packages only in 3.0.0
│   ├── accounts/
│   └── dashboard/
├── checks/                         # Source policy and disposable schema checks
└── tests/                          # Policy and database tests
```

The app labels `accounts` and `dashboard` are model and future migration
namespaces inside one application workflow. While policy is `draft`, QC Tool and
Django framework migration history are disabled together; the installed Django
package still supplies its upstream migration code. After a reviewed freeze in
3.0.1 or later, the complete migration graph becomes the released-schema owner.
CI and startup must never generate migration definitions.

Offline cutover wrappers live under
[`scripts/migration/legacy/`](../../../scripts/migration/legacy/README.md), with
host tests under [`scripts/tests/migration/`](../../../scripts/tests/migration/).
They invoke the central workflow and importer; they do not own another schema.
The [script catalog](../../../scripts/README.md) records their lifecycle.
