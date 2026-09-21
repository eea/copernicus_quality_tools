# QC Tool database lifecycle

This package owns QC Tool's schema lifecycle, deployment commands, checks and
migration documentation. Read `policy.json` to select the applicable workflow.

| Lifecycle stage | Workflow |
| --- | --- |
| `draft` | Develop models without migration files; initialize disposable databases from those models. |
| Release freeze | Generate initial schema snapshots and commit them with the transition to `released`. |
| `released` | Include reviewed forward migrations with schema changes; apply them through one deployment job. |
| Legacy data conversion | Transfer and reconcile data into a fresh target schema as a separate release operation. |

Schema initialization creates tables and standard permissions/roles without
importing products. It does not alter or reset existing draft tables. Use fresh
disposable databases for draft schema changes and preserve local data as needed.

New catalogs remain empty until an administrator uploads product specifications
through **Products → Upload specification**, or an operator deliberately runs a
reviewed import. Bundled JSON recipes do not become catalog products at startup.

Migration files are versioned in Git and packaged in release images. PostgreSQL
stores the resulting schema, application data and record of applied migrations.

## Start here

| Your task | Procedure |
| --- | --- |
| Review every table and column | [Complete table and column dictionary](TABLES.md) |
| Review model ownership, retained data and cleanup candidates | [Application schema](SCHEMA.md) and [database audit](AUDIT.md) |
| Understand what belongs in Git versus PostgreSQL | [Migration philosophy](MIGRATIONS.md#migration-philosophy) |
| Develop a draft schema | [Models-only development](MIGRATIONS.md#draft-schema-development) |
| Check a change on a disposable database | [Local verification](MIGRATIONS.md#local-verification) |
| Prepare the first release | [Create and freeze the first snapshots](MIGRATIONS.md#freeze-the-first-release) |
| Transfer legacy production data | [SQL dump importer](LEGACY_IMPORT.md) and [the zero step](MIGRATIONS.md#one-time-manual-production-cutover) |
| Maintain migrations after the release | [Developer workflow](MIGRATIONS.md#development-after-the-major-release-is-frozen) |
| Build and deploy a release | [Release preparation](MIGRATIONS.md#prepare-a-release) and [release record](RELEASE_TEMPLATE.md) |
| Upgrade PostgreSQL with minimal interruption | [Online rollout](MIGRATIONS.md#online-rollout-sequence) |
| Investigate a failed deployment | [Failure and recovery](MIGRATIONS.md#failure-and-recovery) |

Use the documentation from the same source revision as the release. Other docs
pages link here; this package owns the application-wide procedure.

## Package layout

```text
src/qc_tool/database/
├── README.md                       # Start here
├── SCHEMA.md                       # Table ownership and persistence boundaries
├── TABLES.md                       # Every column, PostgreSQL type, key and index
├── MIGRATIONS.md                   # Developer and operator instructions
├── RELEASE_TEMPLATE.md             # Release-specific decisions and evidence
├── policy.json                     # Lifecycle phase and baseline identities
├── policy.py                       # Policy and Django migration-module selection
├── deployment.py                   # Draft initialization / released apply and locks
├── legacy/                         # Offline legacy SQL-dump conversion
├── apps.py                         # Django command discovery
├── management/commands/database.py # database plan|check|apply
├── management/commands/import_legacy_dump.py # Explicit dry run / fresh-target import
├── migrations/                    # No migration definitions during draft
│   ├── accounts/                  # Accounts migration module
│   └── dashboard/                 # Dashboard migration module
├── checks/                        # History gate and disposable schema checks
└── tests/                         # Policy, initialization and deployment tests
```

The Django app labels `accounts` and `dashboard` have migration modules under
this package. Model ownership may evolve during draft schema development.
At freeze, generate snapshots for the registered model-owning apps. The app
subdirectories support Django's dependency graph; releases use one
application-wide plan and apply job.

There is no second SQL/JSON schema specification to maintain. Django models
describe the desired schema; after freeze, native Django migration files describe
its evolution. Django's framework migrations remain installed upstream and are
enabled for released targets. During draft only, their history is disabled too
so all related tables can be built together from current models.
