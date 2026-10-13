# QC Tool database

QC Tool **v3.0.0 has a new models-only schema**. Django models are its only
schema definition. [policy.json](policy.json) is `draft` with `baselines: {}`;
there are no first-party migration packages, baseline snapshots, legacy import
commands or released-migration execution paths in this version.

The central database package owns fresh initialization and read-only readiness
checks for the entire application, including Django's account tables. It does
not upgrade, repair, reset or adopt an existing database.

```sh
PYTHONPATH=src python3 -m qc_tool.frontend.manage database plan
PYTHONPATH=src python3 -m qc_tool.frontend.manage database apply
PYTHONPATH=src python3 -m qc_tool.frontend.manage database check
```

| Command | Behavior |
| --- | --- |
| `plan` | Read-only: reports whether the database is empty, matches current models, or has an incompatible schema. |
| `apply` | Initializes an entirely empty database. A matching existing schema is a read-only no-op. A partial, foreign or outdated schema is refused. |
| `check` | Read-only: validates the managed model schema and required integrity/access paths. An empty or incompatible database fails. |

An explicit `apply` works for fresh development, test **and production** targets.
Startup checks readiness; it never initializes production automatically. Local
Compose opts into development initialization with
`QC_TOOL_INITIALIZE_ON_STARTUP=yes`. CI and startup never generate migration files.
Use fresh disposable targets after changing models. An empty product catalog
does not mean an empty database: account and history tables may still contain data.

Readiness validates required model structure and declared integrity/access paths.
It does not exhaustively compare field-generated positive-integer checks,
additional constraints, triggers, privileges or storage. A handoff archive has
separate full schema/data reconciliation evidence; the checker alone does not
certify a manually altered database or a complete production installation.

Fresh initialization creates the current tables, standard permissions and roles.
It creates no users, products or deliveries. Administrators upload original
specifications through **Products → Upload specification**; specifications and
uploaded snapshots must never be rewritten.

Legacy conversion is **manual and outside the maintained codebase**. A prepared
native PostgreSQL archive contains the new schema and converted records together.
Restore it into a separate empty database using [MANUAL_RESTORE.md](MANUAL_RESTORE.md).
Do not run initialization before restoring its schema, restore legacy DDL over
this schema, or reset/fake/alter existing databases to simulate a cutover.
Private conversion source/evidence and database copies are excluded from Git.

Initial migration history belongs to a separately reviewed release in **3.0.1
or later**. Its transition from model-created tables must be designed then;
v3.0.0 ships no future migration or automatic adoption mechanism.

## References

| Task | Reference |
| --- | --- |
| Initialize or verify a fresh database | [Initialization runbook](MIGRATIONS.md) |
| Restore the prepared database copy | [Manual PostgreSQL restore](MANUAL_RESTORE.md) |
| Review model ownership | [Application schema](SCHEMA.md) |
| Review stored fields and SQL integrity | [Table dictionary](TABLES.md) |
| Review verified evidence and remaining work | [Audit](AUDIT.md), [v3.0.0 record](releases/3.0.0.md) |
| Record a production installation | [Release template](RELEASE_TEMPLATE.md) |

## Package layout

```text
src/qc_tool/database/
├── policy.json, policy.py          # Models-only source contract
├── deployment.py                  # Empty-schema initializer and readiness inspector
├── apps.py                        # Django management-command discovery
├── management/commands/database.py
├── checks/source.py               # Offline source-layout check
├── checks/schema.py               # Disposable model-created schema verification
├── tests/                         # Offline and database regression checks
└── releases/                      # Release evidence
```

`accounts` and `dashboard` are model namespaces within one database workflow.
Django's migration modules are disabled for all managed application/framework
apps. Native Django `migrate --run-syncdb` is used internally only when the whole
schema is empty; the public operation is `database apply`. It writes no migration
history. Existing schemas never run initialization or its bootstrap signals.
