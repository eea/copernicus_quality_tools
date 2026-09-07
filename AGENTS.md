# Database changes

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

Release preparation generates initial schema snapshots and freezes the policy
in the same reviewed change. Keep release freeze separate from feature work.
The central database package owns the workflow. Model/app ownership may be
refactored during draft schema development; after freeze, preserve established
migration identities and account for compatibility explicitly.

After the explicit freeze, preserve committed migrations and add reviewed
forward migrations with model changes. Use staged compatible schema changes,
resumable backfills, and later cleanup for online PostgreSQL deployments.

Use the application-wide `python3 -m qc_tool.frontend.manage database
plan|check|apply` workflow. CI and startup must never generate migration files.
Legacy data conversion is a separate release operation into a fresh target
schema. Do not reset, fake, or migrate an existing production or developer
database to simulate a cutover. Test against disposable databases only.
