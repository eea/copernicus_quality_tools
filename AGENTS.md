# Product specifications

Never modify product specification files or uploaded specification snapshots.
Keep filename identification rules and other QC Tool integration configuration
outside the specifications; consume their original bytes without rewriting them.

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
Fresh development/test databases are built from current models using
the whole-app database command. Schema creation does not populate products or
alter existing tables; use a fresh disposable database after schema changes.
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
Legacy data conversion is a separate release operation into a fresh target
schema. Do not reset, fake, or migrate an existing production or developer
database to simulate a cutover. Test against disposable databases only.

The unpublished v3.0.0 freeze mistakenly integrated at commit
`41a1427f47ce8e8068ac6605d6bc17377309a69c` is withdrawn by the release owner's
explicit correction. Its exact one-time source-history decision is recorded in
`src/qc_tool/database/history_corrections/3.0.0-models-only.json`. This exception
does not authorize resetting databases or rewriting future released history.
