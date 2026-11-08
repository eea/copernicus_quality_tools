# Database migrations and release upgrades

QC Tool **3.0.0 includes migration management**. Committed native
Django migrations define accounts, catalog, deliveries, publication and transfer
receipts together. Django maintains its framework tables and `django_migrations`
history. Earlier installations of the same 3.0.0 application version may be
history-free. The supported models-only schema is adopted only on a verified
separate copy; its serving database and original files are retained. Future
3.0.1 and 3.1.0 releases extend the committed history with forward migrations.

Use commands, policy and frontend/worker images from the same reviewed revision.
Startup checks readiness. It does not apply pending migrations, adopt an occupied
database or generate migration files.

## Choose the operation

| Target | Supported operation |
| --- | --- |
| Entirely empty new SQLite or PostgreSQL database | `database plan`, explicit `database apply`, then `database check` |
| Current schema and complete installed migration history | `database check`; repeated `apply` is a read-only no-op |
| Supported earlier release | Maintenance, full backup, separate restored candidate, installed migrations, verification, explicit switch |
| Exact supported history-free 3.0.0 schema | Candidate-only strict adoption of reviewed initial history |
| Partial, foreign or unknown schema/history | Stop and retain it; no repair or guessed history |
| Prepared native archive | Restore its own schema into an empty separate database; do not initialize it first |

An empty product catalog is not evidence of an empty database. Users, tokens,
deliveries and history can exist independently of catalog contents.

## Fresh installation

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage database plan
PYTHONPATH=src python3 -m qc_tool.frontend.manage database apply
PYTHONPATH=src python3 -m qc_tool.frontend.manage database check
```

`plan` and `check` are read-only. On an entirely empty target, `apply` uses
Django's migration engine and creates standard permissions and roles. It creates
no users, products or deliveries. A matching managed target is left unchanged;
an occupied unsupported target is refused. PostgreSQL schema work uses the
application-wide advisory lock and bounded lock/statement timeouts.

Production initialization is explicit. Development/test may opt into empty-target
initialization with `QC_TOOL_INITIALIZE_ON_STARTUP=yes`; that option cannot
upgrade an existing database. `QC_TOOL_MIGRATE_ON_STARTUP` remains unsupported.

## Administrator upgrade journey

The Admin migration task runs migrations shipped in the **installed image**.
It does not upload Python/SQL, fetch a release, change images or choose arbitrary
migration targets. Install the reviewed target image pair under the release's
maintenance admission procedure before running its migration plan.

1. Rehearse on disposable representative copies. Record source schema/history,
   target image digests, storage identities and recovery steps. Verify space for
   backup, candidate, indexes and transaction work; isolate external writers.
2. Enable maintenance and wait for positive worker acknowledgement and **Ready**.
   A timeout, banner or HTTP health check does not prove quiescence.
3. Create and verify a native PostgreSQL backup with all retained file sections.
   Review missing historical files, external objects and private recovery material
   explicitly. Retain an independent off-host copy as well.
4. Restore into a new operation-owned candidate. Verify exact original schema/data
   restoration **before** migration. Preserve shared-file identities and pins.
5. Review the supported source and installed Django graph. Initial adoption
   accepts only the exact reviewed 3.0.0 schema with absent history on this
   candidate. Record the complete reviewed initial graph, including framework
   predecessors. Ordinary `--fake-initial` table-existence checks are insufficient
   evidence of equivalence. Never fake history on the serving database.
6. Run native forward migrations on the candidate. Verify target history/schema,
   connected records, administrator access and retained-file checksums. SQL
   transactions do not make filesystem changes transactional.
7. Explicitly review **Switch active database**. Selection changes a private
   deployment pointer and retains the previous database, backup, journals and file
   pins. Maintenance stays enabled.
8. Check login, permitted/denied access, deliveries, reports, submissions and a
   representative QC job with the reviewed images before turning maintenance off.

The first adoption exception applies only to the explicit managed transition and
its strictly verified restored candidate. Legacy conversion stays private manual
operator work outside this codebase.

Supported PostgreSQL predecessors can have `integer` or `bigint` IDs on three
implicit framework join tables: `auth_group_permissions`, `auth_user_groups`
and `auth_user_user_permissions`. Native Django framework history uses `integer`
IDs there; earlier model initialization can retain either known width. Strict
models-only source recognition and managed readiness accept those two
representations only on these three ID columns. Adoption preserves their actual
width and values without altering or narrowing those columns. Other columns and unrecognized widths
remain exact. This accounts for differing Django initialization defaults; it is
not permission to accept arbitrary drift.

For a managed source with pending migrations, its historical migration state
verifies source schema before current models are queried. Source recovery binds
complete native SQL and all retained file roots; the migrated target still
undergoes current-model record/reference validation. A release that makes source
administrator authentication incompatible needs a separately reviewed offline
procedure rather than assuming the new Admin can read the old account schema.

## Failure and recovery

An interrupted or failed upgrade retains the original serving database and holds
maintenance. Preserve the backup, candidate, journals and storage pins. A lost
acknowledgement does not prove rollback: inspect recorded Django history and
verification evidence before retrying. Never erase a pin/journal, clear tables,
fake an unapplied operation or reset a database to make the interface continue.

Migrations are transactional where the backend and migration support it; a whole
multi-migration upgrade is not one universal transaction. Earlier migrations may
have committed. `atomic = False`, irreversible data changes, external services
and filesystem side effects require release-specific recovery. Preserve uncertain
candidates for inspection; a new candidate from the retained verified backup is
the conservative recovery path.

Quick switch-back is restricted to the same maintenance generation before ordinary
work resumes and requires compatible installed code. Across incompatible schemas,
recover using the previous pinned images and retained database/storage under an
offline operator procedure. Reverse migrations cannot reconstruct discarded data
or files. After reopening, an older copy can discard accepted work; use a forward
fix or separately reviewed reconciliation.

## Maintaining future releases

The product calls `3.0.x` minor updates and `3.x.0` major updates. These labels
describe scope; they do not establish database, storage, package or worker
compatibility. A minor update may require migration; a major update may have no
schema operation. Compatibility comes from committed dependencies, explicit
supported-source contracts and verified storage behavior.

For example, a 3.0.1 fix without model changes reuses the committed 3.0.0 graph.
A 3.0.1 model change adds a forward migration; a 3.1.0 release follows the same
workflow with its reviewed source and storage contracts. Do not regenerate the
initial migrations or infer storage compatibility from either version number.

Readiness distinguishes physical drift from reviewed declarations in native
migration state. Declared database defaults and generated columns are checked
against expressions compiled by Django; this inspection does not execute source
defaults or functions. Changed expressions, missing migration definitions,
dependency cycles, conflicting branches and current model fields without their
committed migrations are blockers. An unsupported backend rewrite of a complex
expression requires review rather than guessed equivalence or automatic repair.

Generate and review native migrations in development, commit them with the model
change and test supported upgrade paths. Data migrations use historical models
through `apps.get_model()`. Keep operations bounded and deterministic. For large
PostgreSQL deployments use staged compatible changes, resumable backfills and
later cleanup. Preserve released migration contents, app labels and table names.
When stored business fields change, update the explicit portable transfer field
registry and reviewed semantic compatibility fixtures as part of that release.
Native backups preserve SQL independently; a schema migration does not implicitly
make an older portable package reader understand new fields.

Keep storage transformations separate from SQL migration. This path retains
original specifications, delivery ZIPs, QC artifacts and publications at existing
identities. A future path/format change needs a reviewed resumable procedure,
checksums and old/new reader compatibility. Never edit original specifications
or uploaded snapshots.

## Local verification

Use isolated disposable databases and temporary storage. CI checks committed
source and model drift without creating migration files:

```sh
PYTHONPATH=src python3 -m unittest qc_tool.database.tests.test_source
PYTHONPATH=src python3 -m qc_tool.database.checks.source
PYTHONPATH=src python3 -m qc_tool.frontend.manage makemigrations --check --dry-run
PYTHONPATH=src python3 -m qc_tool.database.checks.schema
PYTHONPATH=src python3 -m qc_tool.frontend.manage test qc_tool.database.tests.integration
```

Repeat fresh initialization, populated source-copy adoption, native forward
migration, drift/history refusal and recovery on supported SQLite/PostgreSQL
backends as applicable. Admin native backup/candidate switching is PostgreSQL-only.
SQLite requires an offline consistent backup and separately reviewed disposable-copy
upgrade procedure. See [testing](../../../docs/development/testing.md) and the
[3.0.0 record](releases/3.0.0.md). CI is not proof of a production restore,
distributed filesystem or live EEA deployment.
