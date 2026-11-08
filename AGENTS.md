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

# Application structure

Organize application code into nested packages by responsibility. Prefer small,
cohesive Python modules, normally below 150 lines, with explicit public imports.
Treat growing files as a reason to review ownership; do not split a cohesive
algorithm or immutable migration history merely to meet a line count.

Keep HTTP handling, presentation, domain decisions and persistence operations in
their owning modules. Share behavior through its domain owner rather than copying
helpers across workflows or adding unrelated functions to a generic utilities
module. Reuse existing services before introducing a new abstraction. Avoid
wildcard exports, dynamic module forwarding and compatibility layers for private
helpers; update internal callers to the actual owner when moving them.

# Repository hygiene

Keep source, required test fixtures and assets, maintained tooling/configuration,
and durable documentation in Git. Do not commit session plans, transcripts,
screenshots, ad hoc verification logs, UI mockups or generated site/report output.
Store temporary session work outside the checkout or in the ignored root `work/`
directory. Put useful design findings in the owning documentation section and
update their links; do not keep a duplicate session report beside them.
Check references before removing old tooling. Preserve original specifications,
test fixtures, private backups and runtime/recovery data during artifact cleanup.

# Administration boundaries

The Admin interface owns user management, role groups, permissions, boundary
packages, notifications, database inspection, storage, backups and maintenance.
Its overview provides these task directions without a header section-navigation
bar. Keep task navigation and automatic authentication/error recovery destinations
inside Admin. Permit one explicit **Back to workspace** control with a back arrow
to leave administration; the Admin brand still links to its overview.
Keep maintenance status visible throughout Admin through the shared shell, with
a guarded turn-off control that returns to the current Admin page.
Do not add other normal-workspace links,
product setup, QC execution or submission-review shortcuts to Admin.

# Database changes

QC Tool **v3.0.0 includes native Django migration management** as the foundation
for later releases such as v3.0.1 and v3.1.0. Earlier v3.0.0 installations may
have a models-only schema without a migration recorder. Distinguish supported
history-free databases from managed databases by strict schema and recorded
history, never by their shared release label alone. Preserve the reviewed initial
migrations and their app identities. Every later model change requires reviewed
forward Django migrations in the same change; CI checks committed history against
the models and startup never generates migration files.

Read `src/qc_tool/database/README.md`, `src/qc_tool/database/policy.json`, and
`src/qc_tool/database/MIGRATIONS.md` before changing persistence or deployment
behavior. The central database package owns the workflow for accounts, catalog,
deliveries, publication and framework tables together.

Use the application-wide `python3 -m qc_tool.frontend.manage database
plan|check|apply` workflow for readiness and fresh initialization. Initialization
requires an entirely empty database and runs committed native migrations. A
matching existing schema/history is a read-only no-op. Partial, foreign, unknown
history or unexplained drift is refused without reset, repair or fake adoption.

Existing installations upgrade only through the reviewed administrator workflow:
ready maintenance, verified native backup and retained-file coverage, restore into
a distinct operation-owned candidate, supported source/history validation,
explicit native forward migration, validation, and separate reviewed selection.
Only an exact supported history-free v3.0.0 restored candidate may adopt the
reviewed initial graph. Never adopt or migrate the serving database automatically.
Keep the source database, backups, operation journals and storage references for
recovery. Django schema migrations do not relocate retained delivery, job,
specification, boundary or publication files.

Preserve committed migrations and add forward migrations with model changes.
Use staged compatible schema changes, resumable backfills, and later cleanup for
PostgreSQL. Release labels alone do not establish schema compatibility. Review
non-atomic operations and external side effects explicitly; reversing a schema
migration is not a substitute for a verified backup and retained source copy.

Legacy conversion stays a manual operation outside the maintained codebase.
Do not reset existing production or developer databases to simulate a cutover.
Test adoption and upgrades against disposable databases only.
