# Database migrations

QC Tool's database lifecycle covers schema development, release freeze, data
conversion and released-schema upgrades. The phase in [`policy.json`](policy.json)
determines the applicable development and deployment workflow.

## Migration philosophy

| Source | Responsibility |
| --- | --- |
| Django models in Git | The desired application schema, editable without migration files during draft development |
| `src/qc_tool/database/migrations/` in Git and the release image | After freeze: reviewed instructions for creating/upgrading that schema |
| PostgreSQL | The actual tables, indexes, constraints and application data |
| PostgreSQL's `django_migrations` table | After freeze: which migration identities have run in this database, and when |
| `policy.json` in Git | Lifecycle phase and established baseline migration identities |
| Release record | Images, compatibility, backfills, exact rollout commands and recovery decisions |

**Developers write and commit migrations in the repository, not in PostgreSQL.**
Django executes those files against PostgreSQL and records their completion.
Do not put migration source code in database stored procedures or maintain SQL
changes in pgAdmin as the normal development workflow. PostgreSQL-specific SQL
can be included in a reviewed Django `RunSQL` migration, with corresponding
Django state changes when needed. Use native operations where available.

The database recorder is bookkeeping, not a schema specification or a copy of
the migration code. A successful `database check` does not prove that someone
has not manually altered a table. Never copy the legacy recorder into a new
release database or edit it to bypass an error.

In `django_migrations`, `app` identifies the Django app, `name` identifies the
migration file, and `applied` records its application time; `id` is the row's
primary key. Django maintains these rows automatically. The table does not
store the Python code, generated SQL, schema diff or application release number.
For a released database, inspect its applied history without changing it:

```sql
SELECT app, name, applied
FROM django_migrations
ORDER BY applied, app, name;
```

Draft initialization does not apply migration history, so an empty recorder
is expected on a freshly initialized draft database.

During draft, **there is no application migration history to maintain**. Django
migration modules are disabled for QC Tool and its framework tables; fresh
schemas are created from current models through `migrate --run-syncdb`. This is
an initialization mechanism for disposable development/test databases, not an
upgrade mechanism. At freeze the normal Django migration graph is enabled,
including Django's own installed migrations, and the released target starts
empty. See Django's [migration module setting](https://docs.djangoproject.com/en/5.2/ref/settings/#migration-modules)
and [schema initialization option](https://docs.djangoproject.com/en/5.2/ref/django-admin/#cmdoption-migrate-run-syncdb).

The "zero" step is a one-time **data conversion/import** into that new schema.
It is neither a chain of old schema migrations nor `migrate <app> zero`, which
would unapply migrations. Plan and rehearse data conversion separately from
schema creation before scheduling the production cutover.

## Choose the workflow

Start here for each change. Run commands from the repository root unless a
section says otherwise. Use this file from the **same commit as the release**.
Repository-relative links refer to documentation and code in that checkout.

| Situation | Follow | Done when |
| --- | --- | --- |
| Draft model/schema change | [Models-only development](#draft-schema-development), then [local verification](#local-verification) | Current models initialize and tests pass on both backends; no migration files |
| First production release | [Freeze](#freeze-the-first-release), [prepare release](#prepare-a-release), then [deployment initialization](../../../docs/deployment/index.md#5-pull-and-initialize-the-database); include [manual cutover](#one-time-manual-production-cutover) when replacing a legacy installation | Target schema and application checks pass; any required data import is reconciled before serving traffic |
| Empty installation after freeze | [Prepare release](#prepare-a-release), then [deployment initialization](../../../docs/deployment/index.md#5-pull-and-initialize-the-database) | Complete schema and roles exist; application smoke tests pass |
| Post-release model/schema change | [Author and review](#development-after-the-major-release-is-frozen), then [prepare release](#prepare-a-release) | Committed forward migrations and compatibility evidence accompany the release |
| Compatible PostgreSQL expansion | [Online rollout](#online-rollout-sequence) | New code works with expanded schema; deferred backfill/contract has an owner |
| SQLite or incompatible schema operation | [Maintenance upgrade](../../../docs/deployment/operations.md#maintenance-procedure) | Writers are stopped for the operation; validation passes before restart |
| Catalog/artifact change or long data backfill | [Operational backfills](#data-changes-and-operational-backfills) | Explicit command is resumable and its data assertions pass |
| Application-only release | [Prepare release](#prepare-a-release) | Drift check passes and migration plan is reviewed, including framework upgrades; no empty migration is added just for a version number |
| Failed check or deployment | [Failure and recovery](#failure-and-recovery) | Cause and database state are understood before a reviewed retry or repair |

During draft the developer supplies model changes and behavior tests. After
freeze the developer also supplies the migration review and upgrade tests. The release
maintainer freezes or selects the reviewed source and compatible image pair.
The deployment operator supplies target configuration, backup/restore evidence,
environment serialization and rollout results. One person may fill all roles;
record them in the [release record](#release-record).

### What each command proves

The table below describes **released** mode. In draft, `database apply` creates
missing tables directly from models, `database plan` explains this behavior,
and `database check` verifies table/column presence only. None of these draft
commands alters existing columns or certifies types, indexes or constraints.
`makemigrations --check --dry-run` has no first-party history to compare during
draft; fresh schema creation and application tests are the checks that matter.


| Command | Effect and success condition |
| --- | --- |
| `makemigrations --check --dry-run` | Writes no migration files; exit 0 means model state matches committed migration state. It does not compare actual database tables. |
| `database plan` | Prints the complete pending dependency graph without applying schema changes. A nonempty plan is expected before an upgrade. |
| `database check` | Exit 0 means no pending migrations and consistent known history. Success may print nothing. It does not verify manual schema edits, imported data or application compatibility. |
| `database apply --traceback` | Applies all pending migrations and runs permission/role bootstrap under the deployment lock. Exit 0 is required before rollout; it is not one transaction for the entire release. |
| `python3 -m qc_tool.database.checks.schema` | On an **empty test database**, checks model initialization in draft, or baseline-to-head upgrade and drift after freeze. Synthetic fixture data is test-only. |

`accounts` and `dashboard` are Django schema namespaces inside one deployment
graph. Migration filenames are not application release versions. There is one
policy, one release record and one apply job for QC Tool, including Django's own
tables. Domain-specific backfills run at the point specified by that release;
they must not introduce independent component release procedures.

## What the database owns

| Owner | Persistent state |
| --- | --- |
| Django `auth`, `contenttypes`, `sessions`, `admin` | Users, groups, permissions, sessions, admin audit history |
| `accounts` | Profiles, personal API tokens, account capability declarations and product/region grants |
| `dashboard` domain packages | Catalog releases, product units and QC definitions; deliveries, jobs, storage references, submissions and conflict history |
| Worker and shared storage | Delivery ZIPs, job artifacts, published submissions and boundary generations; worker scratch PostGIS schemas are disposable job state |

The [application schema](SCHEMA.md) is the table ownership reference. Models
declare explicit business-domain table names independently of Django app labels.
`accounts/models/` owns account models; `dashboard/models.py` discovers the
business models implemented under `dashboard/domain/`. These ownership boundaries
share one database and migration graph. After freeze, changes to app labels or
table names must address content types, permissions, foreign keys and running
application compatibility explicitly.

Schema migrations describe database structure and small, deterministic database
transformations. They do not discover product recipes, read job-result files,
copy submissions, contact S3, or execute QC algorithms. Catalog synchronization
and artifact backfills remain explicit management operations.

## One-time manual production cutover

The "zero" step transfers legacy data into a fresh released schema. Finalize
and freeze that schema before the production cutover rehearsal against
legacy records and storage. The [legacy dump converter](LEGACY_IMPORT.md) can be
developed and tested on disposable draft schemas; repeat the rehearsal against
the frozen release before cutover. Schema initialization must not populate products;
product data enters through the reviewed import or catalog synchronization.


Rehearse the following against a restored source snapshot before scheduling
the production transition. Record the source release, target image digests,
import script revision, row mappings, reconciliation decisions and validation
results as release evidence.

1. Preserve a verified backup of the legacy database and its referenced shared
   data. Provision a **separate, empty** target database and target storage with
   explicit credentials and volume mappings. Do not attach the old database
   volume to the new release.
2. Pin the new frontend and worker images in the target deployment. Start its
   database service, then apply the committed migrations using a one-shot
   frontend container as shown in [Deployment](../../../docs/deployment/index.md). This
   builds the complete target schema, including Django's own tables, permission
   records and canonical role setup. Keep frontend and workers stopped.
3. Map and import the selected legacy records into that schema. Use an explicit
   field and primary-key mapping; a legacy SQL dump is a source for conversion,
   not a schema to restore over the target. Import referenced rows before their
   dependents and repair database sequences after retaining numeric IDs.
4. Reconcile the application invariants below. Bulk SQL, bulk ORM operations
   and fixture imports can bypass service validation and user/role signals.
5. Compare source and target counts, explain omissions, check foreign keys and
   uniqueness, verify representative files and digests, and run authorization
   and workflow smoke tests on the target. `database check` proves migration
   records are current; it does not certify imported data or schema contents.
6. At the final cutover, stop new writes and uploads, drain or deliberately stop
   active jobs, and stop source frontend and workers. Take a coherent final
   database/storage snapshot and repeat the validated import. Run final checks,
   start the target services and switch traffic. Retain the old deployment and
   snapshot for the agreed recovery window without allowing both systems to
   accept writes.

The import reconciliation must cover:

- **Identity and access:** users, password hashes or a deliberate reset policy,
  active/superuser state, default/admin/product-manager membership, direct
  permissions and product/region grants. Resolve permissions by app label and
  codename rather than legacy numeric IDs. Verify staff flags and both allowed
  and denied access. Role names alone do not establish scope.
- **Credentials:** issue new personal API tokens through the account workflow;
  do not copy legacy plaintext API credentials or live sessions. Coordinate
  client credential replacement and worker authentication with the target
  `WORK_DIR`.
- **Catalog and product units:** reconcile canonical product identifiers, authoritative
  releases, expected product units and QC-definition snapshots. Observed delivery product units
  must not manufacture authoritative `ProductUnit` rows. Normalize observed
  identifiers through the current product unit contract, using the explicit
  legacy adapter for historical AOI fields. Keep geographic normalization out
  of new opaque product-unit codes.
- **Deliveries and jobs:** retain ownership and foreign-key relationships,
  timestamps, job state, release/definition provenance, immutable results and
  checksums. Preserve the distinction between the ZIP's verified product unit and the
  latest-job display projection. Do not import an active job as runnable unless
  its execution and boundary-generation dependencies have been reconciled.
- **Submissions and files:** verify published copies, authorizing jobs, expected
  and observed product unit snapshots, digests, conflict decisions and audit events.
  Copy incoming/work/submission storage and boundary generations consistently
  with their database references. Keep unverifiable historical submissions
  fail-closed; do not invent missing provenance or a successful QC result.

Keep the target's freshly generated `django_migrations`, content types and
permission records. Do not import the old migration recorder, fake either
baseline, rewrite applied history, or drop old tables to make startup succeed.
The distinct `0001_major_release` name avoids pretending that the old
`0001_initial` is this baseline; it is not an automatic legacy-schema detector.

Existing developer databases from before this cutover also need a new database
or an explicit manual import. Switching branches or restarting a container does
not convert them. Retain valuable local data before selecting new volumes or
performing a destructive local reset.

## Draft schema development

This workflow applies when `policy.json` declares:

```json
{"phase": "draft", "baselines": {}}
```

For each change:

1. Change the models, domain code and relevant behavior tests. Rename, move or
   restructure model ownership as needed.
2. Do **not** create or edit migration snapshots. CI rejects QC Tool migration
   definitions while the phase is draft.
3. Run [local verification](#local-verification). Tests create the current
   schema on disposable databases, with synthetic records only in the tests.
4. For interactive development after a schema change, select a fresh local
   database and initialize it from the current models. Preserve users, grants
   and other local data you need first, even if there are no products. Restarting
   a container or `database apply` does not alter existing columns. Do not
   automatically reset an existing developer database.
5. Commit the models, code and tests. No migration is needed for that commit.

The same `database plan|check|apply` interface serves both lifecycle phases.
In development/test, `database apply` initializes missing tables and roles
using native Django schema creation. It does not seed products, import old
production data, or generate migration files. Draft databases have no applied
migration history. A table/column readiness check catches missing or renamed
fields; it is not a full type/index/constraint comparison. Recreate disposable
schemas for **any** schema change and do not rely on `--keepdb` across changes.

Local Compose opts into initialization at startup. Draft builds refuse the
whole-app database command in production/secure environments. Do not relabel
production as development to bypass this guard. The phase follows the release
lifecycle rather than a hard-coded branch name.

### Freeze the first release

Release freeze establishes immutable migration history. Perform it as a reviewed
release-preparation change after the schema and application behavior are ready.

1. Finish the models and review the intended first production schema. Confirm
   fresh SQLite/PostgreSQL creation and application tests pass.
2. In the release-preparation working tree, change `policy.json` to `released`
   and declare one initial snapshot for each current model-owning QC Tool app.
   For apps labeled `accounts` and `dashboard`, the policy is:

   ```json
   {
     "phase": "released",
     "baselines": {
       "accounts": "0001_major_release",
       "dashboard": "0001_major_release"
     }
   }
   ```

   Use the registered model-owning app labels and keep the central mapping in
   `policy.py` consistent with them.
3. Generate the first snapshots from those final models using a temporary
   writable development container and an empty SQLite path:

   ```bash
   docker compose -f docker/compose.local.yaml run --rm --no-deps \
     --volume "$PWD:/usr/local/src/copernicus_quality_tools:rw" \
     -e QC_TOOL_ENVIRONMENT=test -e DB_ENGINE=sqlite \
     -e FRONTEND_DB_PATH=/tmp/qc-tool-first-snapshot.sqlite3 \
     -e WORK_DIR=/tmp/qc-tool-first-snapshot-work \
     frontend python3 -m qc_tool.frontend.manage makemigrations --name major_release
   ```

   Changing the policy first enables normal Django migration generation in this
   process. It writes `0001_major_release.py` into the central app subpackages.
   Generation does not apply anything to the database. Do not run application
   services from this incomplete candidate before its snapshots are verified.
4. Review the complete initial schema and dependencies, and verify that the
   policy mapping matches the generated filenames. Keep data import out of the
   schema snapshots. Run the history gate, fresh released-schema checks and
   regression suites on both backends.
5. Commit policy and snapshots **together in the reviewed freeze change**.
   CI permits this transition from a draft without migrations to exactly the
   declared initial snapshots. After it lands, these files and the baseline
   mapping are immutable; do not return to draft.
6. Build/rehearse the release as described below. Provision a **fresh released
   target** and apply its committed graph. For a legacy cutover, complete the
   zero data-transfer step before switching production traffic.

Do not fake these snapshots onto a model-created draft database. Its lack of
migration history is intentional; it is not a database supported for in-place
release upgrade. Reuse selected data only through an explicit import into the
fresh released target.

## Development after the major release is frozen

Every model change carries its reviewed migration in the same commit. Generate
it once in development; CI and deployment apply the committed files. Django
compares models with migration state, not with the current database schema.
[Django migration workflow](https://docs.djangoproject.com/en/5.2/topics/migrations/#workflow).

The local checkout is normally mounted read-only. From the repository root,
temporarily make it writable in a disposable frontend container to generate a
named migration. These explicit SQLite settings avoid consulting the persistent
local database during generation:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps \
  --volume "$PWD:/usr/local/src/copernicus_quality_tools:rw" \
  -e QC_TOOL_ENVIRONMENT=test -e DB_ENGINE=sqlite \
  -e FRONTEND_DB_PATH=/tmp/qc-tool-authoring.sqlite3 \
  -e WORK_DIR=/tmp/qc-tool-authoring-work \
  frontend python3 -m qc_tool.frontend.manage makemigrations \
  --name add_review_state
```

Omitting app labels discovers changes across the whole QC Tool. Django writes
any required files into `src/qc_tool/database/migrations/<app_label>/` through
`MIGRATION_MODULES`, and orders them by dependencies. When adding a new Django
app after release freeze, configure its migration module in this central package
before generating migrations; keep the app label stable. Keep `policy.json`'s
baseline mapping unchanged: it records the first release, not the latest set
of apps or migration heads. Do not reintroduce
migration directories under frontend or worker components.
The command override bypasses normal frontend startup. The writable override is
only for this development task; keep ordinary runtime mounts read-only. On
Linux, ensure generated files remain editable by the checkout owner. A writable
host environment with the supported Python and pinned frontend requirements is
also suitable.

Review dependencies and every operation before applying anything. Inspect SQL
for each generated migration, replacing the example app/name with its actual
identity; this command also works while the frontend service is stopped:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps \
  -e QC_TOOL_ENVIRONMENT=test -e DB_ENGINE=sqlite \
  -e FRONTEND_DB_PATH=/tmp/qc-tool-sql-review.sqlite3 \
  -e WORK_DIR=/tmp/qc-tool-sql-review-work \
  frontend python3 -m qc_tool.frontend.manage sqlmigrate dashboard <migration_name>
```

Treat a detected delete/create pair carefully when the intent is a rename.
Review nullability, defaults, uniqueness, index cost, lock duration and rollback
behavior with realistic row counts. Include migration tests for meaningful
data transformations: start at the predecessor, create representative old
records, apply the migration, and verify both preserved and transformed facts.
The SQLite SQL preview does not show PostgreSQL lock behavior or necessarily
support PostgreSQL-only operations. Review PostgreSQL SQL against the isolated
database in [local verification](#local-verification), then rehearse the upgrade
from the last released state. Commit the model, migration, transition tests and
release notes together. Once checks pass, use the same one-shot deployment
procedure for the local database if its data is meant to be upgraded.

### Data changes and operational backfills

Use `RunPython` only for bounded database changes required by the schema.
Resolve historical models with `apps.get_model()` and use
`schema_editor.connection.alias`; do not import current application models or
services into a migration. Declare dependencies on every affected app and
provide a valid reverse operation or explicitly document irreversibility.
[Django historical models](https://docs.djangoproject.com/en/5.2/topics/migrations/#historical-models).

Long-running or external-data work belongs in a separately invoked management
command. Make it bounded, resumable and idempotent, with a dry run and progress
reporting that excludes secrets. `backfill_product_unit_metadata` is the current example
for historical job artifacts; `sync_product_catalog` explicitly imports an
operator-provided catalog. Neither replaces the manual legacy data transfer.

For incompatible changes, use an expand/backfill/contract sequence:

1. Add compatible nullable fields or new tables and deploy code that tolerates
   both states.
2. Run and verify the operational backfill, then switch readers/writers in a
   compatible release.
3. Enforce constraints or remove obsolete fields in a later release after the
   rollback window and all clients have moved forward.

### History and conflicts

After the explicit release freeze, migration files are append-only.
Do not edit, delete or renumber an existing migration to fix deployed state;
add a corrective migration. Future major version numbers do not authorize
another reset. The CI history guard reads the centralized policy and compares with the PR
base/push predecessor. It lives in [`checks/history.py`](checks/history.py) and
runs from the repository root as
`PYTHONPATH=src python3 -m qc_tool.database.checks.history --base <commit>`.
Before freeze it requires no migration definitions; the freeze introduces the
first snapshots; subsequent changes preserve history and allow additions.

When branches create sibling migrations, update from the shared branch and
inspect the dependency graph. A reviewed merge migration is appropriate only
if both operation sets commute; incompatible changes need an explicit
resolution and migration tests. Never resolve a conflict by deleting migration
recorder rows. Retain callable imports and custom fields referenced by history.
Any eventual squashing needs its own compatibility and deployment plan.

## Local verification

Prerequisites: Git and Python 3 on the host, Docker Compose, and the supported
local frontend image built as described in
[local development](../../../docs/getting-started/local-development.md).
Commands below use the mounted checkout and bypass frontend startup; no web
service needs to be running. These are test/rehearsal commands, not deployment
commands. Do not substitute production credentials or volumes.

### History policy

Fetch the current PR target and compare your proposed working tree with it:

```bash
git fetch origin dev
QC_MIGRATION_BASE=$(git merge-base HEAD origin/dev)
PYTHONPATH=src python3 -m unittest qc_tool.database.tests.test_history
PYTHONPATH=src python3 -m qc_tool.database.checks.history --base "$QC_MIGRATION_BASE"
git diff --check
```

Run each command successfully before continuing. For an exact CI reproduction,
use its PR base SHA or push-before SHA instead. The guard needs full Git history;
it rejects a missing/all-zero comparison SHA. A new branch's first push is not
a release gate: open a PR against the existing target. After release freeze,
the comparison must include established history; do not choose an older commit
to make a rewrite pass. A local pass does not replace the CI comparison.

### SQLite: fresh schema and package checks

This one-shot container owns a temporary SQLite file and work directory; `--rm`
discards them. Running it again starts empty. The checkout remains read-only.

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps \
  -e QC_TOOL_ENVIRONMENT=test -e DB_ENGINE=sqlite \
  -e FRONTEND_DB_PATH=/tmp/qc-tool-verification.sqlite3 \
  -e WORK_DIR=/tmp/qc-tool-verification-work \
  frontend sh -eu -c '
    python3 -m qc_tool.database.checks.schema
    python3 -m qc_tool.frontend.manage database plan
    python3 -m qc_tool.frontend.manage database check
    python3 -m qc_tool.frontend.manage makemigrations --check --dry-run
    python3 -m qc_tool.frontend.manage test qc_tool.database.tests.integration --noinput
  '
```

Expected: in draft the probe reports current-model schema and synthetic-data
checks passed; after freeze it reports baseline upgrade and drift checks passed; the plan explains draft initialization or has no pending released operations; the tests pass with
PostgreSQL-only cases skipped. `sh -eu` stops the block at the first failure.

### PostgreSQL: isolated database and regression suite

The local `userdb` service must be healthy first. Start just that service with
`docker compose -f docker/compose.local.yaml up --detach userdb` if needed; do
not start or recreate application services to run these checks. The following
subshell creates a randomly named test database on that local server, explicitly
passes its identity into the one-shot frontend container, and drops only that
database on exit. It reads the database user from the local service environment.

```bash
(
  set -eu
  qc_local() { docker compose -f docker/compose.local.yaml "$@"; }
  QC_MIGRATION_TEST_DB="qc_migration_verify_$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')"
  printf 'Disposable database: %s\n' "$QC_MIGRATION_TEST_DB"
  qc_local exec -T userdb sh -eu -c \
    'createdb --username "$POSTGRES_USER" "$1"' sh "$QC_MIGRATION_TEST_DB"
  cleanup_qc_migration_test() {
    qc_local exec -T userdb sh -eu -c \
      'dropdb --username "$POSTGRES_USER" "$1"' sh "$QC_MIGRATION_TEST_DB"
  }
  trap cleanup_qc_migration_test EXIT
  qc_local run --rm --no-deps \
    -e QC_TOOL_ENVIRONMENT=test -e DB_ENGINE=postgres \
    -e POSTGRES_DB="$QC_MIGRATION_TEST_DB" \
    -e WORK_DIR=/tmp/qc-tool-verification-work \
    frontend sh -eu -c '
      python3 -m qc_tool.database.checks.schema
      python3 -m qc_tool.frontend.manage database plan
      python3 -m qc_tool.frontend.manage database check
      python3 -m qc_tool.frontend.manage makemigrations --check --dry-run
      python3 -m qc_tool.frontend.manage test \
        qc_tool.database.tests.integration \
        qc_tool.frontend.accounts.tests \
        qc_tool.frontend.dashboard.services.tests \
        qc_tool.frontend.dashboard.tests --noinput
    '
)
```

Expected: schema probe and all tests pass without the PostgreSQL-specific skips.
The schema is created from models in draft and from committed history after freeze.
Django creates and removes its own `test_<random-name>` database for regression
tests. If a forced interruption prevents cleanup, inspect the printed database
name and remove only that test database and its Django test counterpart; never
drop the normal local `qc_tool` database. For a PostgreSQL-only SQL review, run
`sqlmigrate <app_label> <migration_name>` inside this same isolated container
before the tests, recording its output in the PR.

The CI matrix runs the full suite on **both** backends plus static/deployment
checks. The quicker local SQLite command above covers the database package;
use the same four test labels there for the full SQLite regression suite.
Changes affecting worker behavior also require the relevant
[worker tests](../../../docs/development/testing.md#worker-infrastructuresecurity-tests).

### Maintaining migration test fixtures

After freeze, keep `seed_baseline()` in `checks/schema.py` expressed in the
historical first-release schema. It must not start creating records with new
fields just because current models changed. If a reviewed migration renames,
removes or transforms a seeded value, adapt the **successor assertions** in
`verify_rows()` to check the intended preserved/transformed facts and add a
focused predecessor-to-successor migration test. Do not delete the assertion
simply to make CI pass. Before freeze, this is a current-model fixture; update it normally with the
models. Only freeze makes its input historical.

In released mode, framework apps are initialized at their supported migration
heads before the historical seed. Future QC Tool apps are applied after the seed, together with
later QC migrations. This probe cannot prove compatibility with every older
Django version or every production dataset. Rehearse from each supported
starting release, especially when upgrading Django or PostgreSQL.

## Prepare a release

Do this for every production release, including changes with no new migrations.
An initial release requires schema freeze; replacing a legacy installation also
requires the manual cutover. The release version is a product decision; use a
major version for breaking changes according to the project's release history.
It is independent of migration numbers. Do not reset history for later major
versions or rewrite published image tags to fix a failed release.

1. Complete a [release record](#release-record). State the supported previous
   releases, migration plan, old/new frontend and worker compatibility, required
   backfills, rollout path, acceptance checks and rollback boundary. Review
   permission bootstrap as well as DDL: `database apply` can synchronize role
   permissions even when the schema plan is empty.
2. Merge reviewed changes and obtain passing CI for the exact candidate source.
   Resolve every history/drift failure. Keep a contraction out of an expansion
   release image. Require the two backend CI jobs in repository branch
   protection; that hosting setting is maintained outside this source tree.
3. Select a clean, committed source revision available on GitHub. Build the
   frontend and worker from the same revision, or explicitly record/test why a
   previously built worker remains compatible. The Dockerfiles download source
   using `VERSION`; use the **commit SHA**, not `dev`, `master` or a moving tag.
   Build contexts and Dockerfiles must also come from that selected revision.
4. Verify the packaged artifacts **without a checkout bind mount**. The CI
   frontend suite mounts the candidate checkout and therefore does not alone
   prove that a published image contains the right source and policy.
5. Rehearse on isolated copies of the last released database and referenced
   storage, using the exact candidate images. Verify restore, old/new access
   policy and worker flows, migration duration, backfill resume and data
   assertions. The baseline probe is not a replacement for this rehearsal.
6. Publish reviewed versioned images through the trusted registry workflow,
   record the resulting immutable digests, and pin those digests in deployment
   configuration. Promote the same artifacts through staging and production.
   Record the Git release tag/source mapping; do not rebuild between stages.
7. Follow the selected rollout procedure. On any failure, stop the rollout and
   use [recovery](#failure-and-recovery). Complete the release record with actual
   results before closing deployment and retain the recovery assets for its
   stated window.

For example, from that clean selected checkout, these commands build local
candidate images; they do not publish or deploy them:

```bash
(
  set -eu
  test -z "$(git status --porcelain)"
  QC_RELEASE_SOURCE=$(git rev-parse HEAD)
  docker build --build-arg VERSION="$QC_RELEASE_SOURCE" \
    --file docker/Dockerfile.frontend \
    --tag "qc-tool-frontend:$QC_RELEASE_SOURCE" docker
  docker build --build-arg VERSION="$QC_RELEASE_SOURCE" \
    --file docker/Dockerfile.worker \
    --tag "qc-tool-worker:$QC_RELEASE_SOURCE" docker
)
```

Verify the frontend artifact with isolated container-local storage. This requires
the frozen `released` policy and rejects images whose policy is `draft`:

```bash
QC_RELEASE_SOURCE=$(git rev-parse HEAD)
docker run --rm \
  -e QC_TOOL_ENVIRONMENT=test -e DB_ENGINE=sqlite \
  -e FRONTEND_DB_PATH=/tmp/qc-tool-artifact.sqlite3 \
  -e WORK_DIR=/tmp/qc-tool-artifact-work \
  -e DJANGO_SECRET_KEY=artifact-check-only \
  -e DJANGO_ALLOWED_HOSTS=testserver,localhost \
  "qc-tool-frontend:$QC_RELEASE_SOURCE" sh -eu -c '
    python3 -c "from qc_tool.database.policy import load_policy; assert load_policy()[\"phase\"] == \"released\""
    python3 -m qc_tool.database.checks.schema
    python3 -m qc_tool.frontend.manage check
    python3 -m qc_tool.frontend.manage collectstatic --noinput
  '
```

Also verify `/etc/qc_tool_version.txt` in both images matches the recorded SHA
and run the relevant worker regression/smoke tests. Archive the results before
publishing. Image registry credentials, publication automation, release tags
and production target configuration are operator-owned; the repository's
current GitHub workflow tests changes to `dev` and does not publish or deploy
releases. The existing Docker build hook accepts a branch name, so it must be
configured to use the same immutable source or be bypassed by the build above.

### Release record

Use [RELEASE_TEMPLATE.md](RELEASE_TEMPLATE.md) for the release PR and deployment
evidence. It is the application-wide specification of **how this release is
operated**, while committed native Django migrations remain the executable
schema history. Fill in the actual deployment commands, database identity,
secret references, image digests, compatibility window and recovery decisions.
Generic documentation cannot supply site-specific credentials or legacy field
mappings; complete those fields during the rehearsal, before deployment.

## CI and deployment contract

The [frontend workflow](../../../.github/workflows/integration-tests.yml) checks
model drift, migration-history immutability, Django/static checks and the full
frontend suite, including `qc_tool.database.tests.integration`, on SQLite and
PostgreSQL. Git-dependent history unit tests run separately on the host as
`PYTHONPATH=src python3 -m unittest qc_tool.database.tests.test_history`; the
frontend image does not require Git. The dedicated
[`checks/schema.py`](checks/schema.py)
check (`python3 -m qc_tool.database.checks.schema` in the frontend runtime)
starts with an empty disposable test database. In draft it creates all models
and checks synthetic data/roles and repeated initialization. After freeze it
applies the initial snapshots, inserts historical records, upgrades to the latest
graph and checks preservation and repeated schema application. It requires
`QC_TOOL_ENVIRONMENT=test` and refuses a populated database. Never point it at
a developer's persistent database or production. Add predecessor-to-successor
test cases when a particular migration needs richer fixtures than this general
baseline check.

Deployment runs one serialized `database apply` job with the **same pinned
frontend image** that will serve requests. For compatible changes, keep the
previous application serving while the expansion runs, following the online
sequence below. The manual major cutover, SQLite changes, and incompatible
changes use the maintenance procedure instead. CI validates changes; it does
not access production, and the repository does not supply a deployment
orchestrator or configure a traffic router.

Production frontend startup runs `database check` and refuses pending
migrations. It never runs `makemigrations`. Local Compose explicitly opts into
draft initialization (or released migrations) at startup with `QC_TOOL_MIGRATE_ON_STARTUP=yes`, which the
entry script accepts only in `development` or `test` environments.

Record migration-job output, image digest, database identity, backup reference
and smoke-test results with each deployment. Application-image rollback is
allowed only while the schema remains compatible. Otherwise use a rehearsed
restore of the matching database and shared data, accounting for writes since
the snapshot. Do not assume that reversing a migration restores deleted data.

## Nearly zero downtime: PostgreSQL online migration path

Nearly zero downtime is a release design requirement, not a flag on `migrate`.
It is achievable for compatible, bounded changes on PostgreSQL. The manual
legacy cutover remains a planned maintenance event. SQLite schema changes use
maintenance because Django may rebuild tables; do not treat the SQLite CI pass
as evidence of production lock behavior.

Use at least three independently deployable steps for a renamed or replaced
field. Example: replacing `Delivery.product_ident` with a new representation:

| Step | Database | Application and worker behavior | Exit criteria |
| --- | --- | --- | --- |
| Expand | Add the new nullable field/table; retain the old field and constraints | Old code continues to work; new code writes both and reads the new value with fallback | Old/new code smoke tests pass against expanded schema |
| Backfill and switch | Fill existing rows in bounded batches; validate completeness | Dual writes remain enabled; switch readers only after reconciliation | No missing values, no divergent writes, acceptable lag and latency |
| Contract, later release | Drop obsolete field/index or tighten constraints | All readers and writers already use the new form; old code is outside the rollback window | No old web process, worker, API integration or maintenance job can still use the old schema |

For this example, keep the steps in separate releases. Keep the contract
migration out of the
image used for the expansion job: `database apply` applies **all** pending
migrations. Coordinate schema changes with queued/running job contracts,
worker versions, upload resumability, persisted result snapshots and submission
publication; frontend schema compatibility alone is insufficient.

### Online rollout sequence

1. Test the proposed graph on an isolated copy of the last released database,
   including data volume, old/new application versions and worker job flows.
   The CI baseline probe is useful but does not replace release-to-release
   fixtures and staging load tests. Record measured lock and backfill duration.
2. Confirm the deployed code tolerates the expansion. Pin the new image,
   capture backup/recovery evidence, and acquire the deployment runner's
   environment lock. Keep the old application serving.
3. Run `database plan` and then one `database apply` job from the new image.
   On failure, stop the rollout. Keep old code serving only if its documented
   compatibility contract still holds; inspect partial non-atomic operations.
4. After `database check` succeeds, deploy the compatible application version,
   run health checks and switch/drain traffic according to the platform.
5. Run separately scheduled, idempotent backfills with checkpoints, bounded
   batches, short transactions and rate limits. Observe database load,
   replication lag, deadlocks, error rate and request latency. Verify completion
   before switching reads and retain dual writes through the rollback window.
6. Schedule contract work in a later release only after proving the old schema
   has no users. Repeat the same review, staging and migration-job gates.

The current QC Tool deployment uses one frontend process because its WSGI
module owns a background status-refresh loop. Plain Compose recreation can
still cause a short application interruption. Truly seamless application
rollouts also require a health-gated traffic router and separating that loop
into a single scheduler; those infrastructure changes are not implemented by
this migration policy. Do not scale frontend replicas just to hide a restart.

### Deployment command setup

Set these values to the reviewed target configuration from the release record.
Use the same project, environment file and manifest set for every operation.
For the first manual cutover, select a **new** target project and volumes. For a
normal upgrade, retain the established project and persistence identities.

```bash
QC_RELEASE_PROJECT=qc_tool_app
QC_RELEASE_ENV_FILE=/secure/path/qc-tool.env
QC_RELEASE_COMPOSE_FILE=docker/docker-compose.eea.yml

qc_compose() {
  docker compose \
    --project-name "$QC_RELEASE_PROJECT" \
    --env-file "$QC_RELEASE_ENV_FILE" \
    -f "$QC_RELEASE_COMPOSE_FILE" \
    "$@"
}

qc_compose config --quiet
```

Use the deployment's customized manifest with pinned image digests, not an
unreviewed checked-in example. If it has multiple override files, include all
of them in the function. Inspect database identity, storage and rendered image
references; keep rendered secret values out of release evidence. The target
database must already be available; first installation setup is in
[Deployment](../../../docs/deployment/index.md).

For a compatible online upgrade, acquire the deployment environment lock,
complete backup/rehearsal requirements and pull the pinned images. The old
application remains serving. Inspect the plan before executing the next block:

```bash
qc_compose pull &&
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database plan
```

After plan review, run the single migration job and gate its follow-up check:

```bash
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database apply --traceback &&
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database check
```

Capture output and exit status from the first attempt in restricted deployment
logs. Do not append a service restart to this block: verify release-specific
data and permission assertions before the health-gated application rollout.
Use the platform's rollout procedure; Compose recreation has the application
interruption described above. For SQLite or incompatible work, follow the
[maintenance procedure](../../../docs/deployment/operations.md#maintenance-procedure).

### Lock and transaction discipline

`database apply` holds a PostgreSQL **session advisory lock** shared by every
release of QC Tool for the duration of migration and permission bootstrap. A
second cooperating migration job fails immediately. Use a direct PostgreSQL
connection or session-mode pool for the job; transaction-mode pooling cannot
reliably retain this session lock. The deployment environment lock is still
required, and direct raw `migrate` commands bypass this protection.

Defaults are a 5-second `lock_timeout` and a 300-second `statement_timeout` per
SQL statement. They limit lock waiting and statement duration, not total job
time. With `qc_compose` defined above, an operator can choose reviewed, positive
bounds on the **initial** apply job, for example:

```bash
qc_compose run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage database apply --traceback \
  --lock-timeout-ms 2000 --statement-timeout-ms 600000
```

A queued exclusive lock can still affect live requests briefly. Stop and
investigate a timeout instead of using an unbounded wait or endless retries.
The command restores session settings and releases its lock on completion;
connection loss releases the PostgreSQL session lock. It does not make unsafe
DDL online or automatically reverse a partially committed operation.

Review these PostgreSQL concerns explicitly:

- Use Django's PostgreSQL concurrent index operations in a non-atomic migration
  for large live tables. Failed concurrent builds can leave an invalid index;
  inspect and repair it before retrying instead of blindly rerunning.
- Large uniqueness/foreign-key/check changes need a staged validation plan.
  Review `NOT VALID`/`VALIDATE CONSTRAINT` or an appropriate concurrent unique
  index attachment where supported, including Django migration-state handling.
- Separate large data transformations from schema transactions. Avoid full
  table rewrites, mandatory fields without a population plan and operations
  that hold locks throughout a long backfill.
- Do not assume reversible schema implies reversible business data. Prefer a
  compatible application rollback during expansion and a reviewed forward
  repair after contract; a restore requires handling intervening writes.

References: [PostgreSQL concurrent indexes](https://www.postgresql.org/docs/14/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY),
[PostgreSQL timeouts](https://www.postgresql.org/docs/14/runtime-config-client.html),
and [Django PostgreSQL migration operations](https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/operations/).

## Failure and recovery

Stop promotion on the first failed check or apply. Preserve the candidate image
digest, target database identity, command, exit status and migration output.
Use `database apply --traceback` **on the initial attempt**: the normal CLI
otherwise wraps a database exception in a short generic error. Tracebacks can
include SQL/data details, so use restricted operator logs and redact them before
sharing. Do not rerun a partially applied migration just to obtain diagnostics.

While investigating, keep maintenance deployments stopped. An online expansion
can leave the old application serving only while its documented schema **and
permission** compatibility holds. Stop new writes if that cannot be established.
Inspect PostgreSQL logs and the failed operation with the database operator.
`database plan`/`database check` are useful read-only checks once connectivity is
available; they cannot prove that a partly committed operation or imported data
is correct.

| Symptom | Required response |
| --- | --- |
| Draft production guard | Follow the explicit release freeze after review. Never relabel production as test/development. |
| Draft history gate rejects a migration | Remove the uncommitted draft migration proposal and keep the model change. Generate the first snapshots at release freeze. Never remove released history. |
| Released history gate rejects a changed file | Restore that file's committed bytes; add a reviewed forward change. Use the correct comparison SHA and fetch missing history. |
| Model drift | In draft, verify current models on a fresh database. After freeze, author the missing forward migration. A raw database edit cannot fix this check. |
| Conflicting dependency heads | Reconcile branch history and operations in development, test the merged graph and ship a corrected image. Do not choose an arbitrary app target in production. |
| Probe refuses a nonempty database | Check the environment and database name. Run it on a new disposable database; do not clear the current database to satisfy it. |
| Probe fails after an intentional rename/transformation | Preserve historical seed data and add explicit successor assertions and predecessor tests as described above. Do not suppress data-preservation checks. |
| Frontend refuses pending migrations or `exec` finds no container | In draft, initialize a fresh development schema after model changes. After freeze, use a one-shot container with the pinned release for plan/apply/check. Do not enable startup migration in production. |
| Another migration job holds the lock | Identify the owning deployment and wait for its operator to finish or recover it. Do not launch competing raw `migrate` commands or terminate sessions blindly. |
| DDL timeout, deadlock or connection failure | Inspect the blocked/failed operation and committed state. Correct the lock/operation plan before a bounded, supervised retry. Earlier migrations may already have committed. |
| Non-atomic migration partly applied | Inspect each operation, including invalid concurrent indexes. Reconcile partial state through a reviewed recovery procedure so the unchanged pending migration can complete, or restore the rehearsed backup. A later migration alone cannot bypass a failing predecessor. |
| `database check` passes after an apply error | The failure may have happened in post-migrate role bootstrap after schema recording. Verify permissions and data; fix the cause and rerun the supported idempotent apply/bootstrap only after review. Check success alone is not release acceptance. |
| Application smoke test fails after apply | Use image-only rollback only if the old code and roles remain compatible. Otherwise stop writes and use the recorded forward-repair or database/storage restore procedure. |

After a transactional migration fails, PostgreSQL normally rolls back that
migration's transaction; **earlier migrations remain applied**. Non-atomic
operations and external backfills can leave additional partial state. Never
assume the entire release rolled back, and never edit recorder rows, fake a
baseline, or reverse migrations as a generic incident fix.

A restore must use a compatible database **and** shared-data snapshot, account
for intervening writes, and include the selected application/worker images and
credential configuration. Keep the replacement target isolated until its
checks pass. After recovery, repeat migration-state, permission, data and
application acceptance checks and record the incident and final decision in the
release record. Schedule deferred contraction only after the documented rollback
window closes and all old readers/writers have been retired.
