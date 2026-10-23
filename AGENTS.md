# Product specifications

Never modify product specification files or uploaded specification snapshots.
Keep filename identification rules and other QC Tool integration configuration
outside the specifications; consume their original bytes without rewriting them.

# QC check ownership

Keep `src/qc_tool/vector/` and `src/qc_tool/raster/` focused on QC checks.
Avoid edits there unless required by a check or a necessary integration change.
Place reusable application and worker functionality in its owning package outside
the check folders; extract existing shared functionality when it is needed.
Preserve check identities, parameters and result semantics when changing imports.

# Administration boundaries

The Admin interface owns users, role groups, permissions, and database import,
export, backups and maintenance. Keep task navigation and automatic
authentication/error recovery destinations inside Admin. Permit one explicit
**Back to workspace** control with a back arrow to leave administration; the
Admin brand still links to its overview. Do not add other normal-workspace links,
product/boundary setup, QC execution or submission-review shortcuts to Admin.

# Database changes

QC Tool **v3.0.0 uses a completely new, models-only schema**. Keep its policy
`draft` with no baselines, first-party migration definitions or initial schema
snapshots. The first migration-managed release can be **v3.0.1 or later**, with
an explicit reviewed initialization/adoption procedure for its supported source
databases. Do not infer a schema freeze from the v3.0.0 version or branch name.

Read `src/qc_tool/database/README.md`, `src/qc_tool/database/policy.json`, and
`src/qc_tool/database/MIGRATIONS.md` before changing persistence or
deployment behavior. They govern QC Tool as one application, across components.

When `policy.json` declares `draft`, keep no first-party migration definitions
or baseline snapshots. Change models and architecture directly.
Fresh databases, including new production installations, are built from current
models using the whole-app database command. Initialization requires an entirely
empty database. A matching existing schema is a read-only no-op; a partial,
foreign or outdated schema is refused. Schema creation does not populate products
or alter existing tables; use a fresh disposable database after schema changes.
Do not reset an existing database automatically, even if its product catalog
is empty: users and other data can still exist.

For v3.0.1 or later, the explicit migration-management transition introduces
the reviewed schema history and changes the policy in the same reviewed change.
Keep that transition separate from v3.0.0 feature work.
The central database package owns the workflow. Model/app ownership may be
refactored during draft schema development; after freeze, preserve established
migration identities and account for compatibility explicitly.

After that explicit transition, preserve committed migrations and add reviewed
forward migrations with model changes. Use staged compatible schema changes,
resumable backfills, and later cleanup for online PostgreSQL deployments.

Use the application-wide `python3 -m qc_tool.frontend.manage database
plan|check|apply` workflow. CI and startup must never generate migration files.
Legacy data conversion is a manual operation outside the maintained codebase.
Deliver a verified native PostgreSQL copy for manual restore into a fresh target.
Do not retain legacy converters or prebuild future migration machinery in v3.0.0.
Do not reset, fake, or migrate an existing production or developer
database to simulate a cutover. Test against disposable databases only.
