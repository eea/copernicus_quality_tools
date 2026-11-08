---
title: Database migrations
parent: Development
nav_order: 5
---

# Database migrations

The current QC Tool **3.0.0 includes committed native Django migrations** and
explicit adoption of the supported history-free schema from earlier installations
of that same application version. The central [database package](../../src/qc_tool/database/README.md)
owns validation and the [migration runbook](../../src/qc_tool/database/MIGRATIONS.md)
owns the procedure. Read them from the same revision as the release image.

| Task | Instructions |
| --- | --- |
| Change a model | Generate and review a Django migration in development; commit it with the model and upgrade tests |
| Check committed model state | `manage makemigrations --check --dry-run`; CI never generates files |
| Inspect a database | Read-only `database plan` and `database check` |
| Initialize an installation | Explicit `database apply` on an entirely empty target, then `database check` |
| Upgrade a supported release | Maintenance, full backup, separate restored candidate, installed migrations, verification, explicit switch |
| Adopt history-free 3.0.0 | Exact supported schema on an operation-owned verified candidate only |
| Prepare a release | Record source contract, graph, images, storage coverage and recovery evidence in the [release template](../../src/qc_tool/database/RELEASE_TEMPLATE.md) |

Startup never applies pending migrations. Unknown drift/history is refused.
The project's minor `3.0.x` and major `3.x.0` naming is independent of migration
graph and storage compatibility.

SQL records refer to original specifications, ZIPs, QC results and retained
publications outside SQL. Transactions cannot roll files back. The upgrade path
preserves their identities and bytes and retains pins for inactive databases.
A storage path/format change needs a separate reviewed procedure. Legacy conversion
stays outside the maintained application.

Use disposable SQLite/PostgreSQL targets for tests. The Admin native backup and
candidate-switch journey requires PostgreSQL; engine support for SQLite does not
imply a browser upgrade workflow. See [testing](testing.md),
[deployment](../deployment/index.md), [maintenance](../deployment/maintenance.md)
and [operations](../deployment/operations.md#upgrades).
