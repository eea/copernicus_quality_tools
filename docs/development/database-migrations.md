---
title: Database initialization
parent: Development
nav_order: 5
---

# Database initialization

The [QC Tool database guide](../../src/qc_tool/database/README.md) owns the
models-only policy, initialization command, schema checks and release evidence
for the whole application. **3.0.0 contains no migration framework, definitions,
initial snapshots or legacy converter.** Current Django models define the schema.

| Task | Instructions |
| --- | --- |
| Change a model | Change the owning model and verify a new disposable target; initialization does not upgrade existing databases |
| Inspect an existing database | Run `database plan` and `database check`; both inspect schema without changing data or repairing it |
| Initialize a new installation | Run `database plan`, then `database apply` against an entirely empty target, followed by `database check` |
| Use a prepared database copy | Follow the [manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md); validate schema, records and corresponding storage before cutover |
| Prepare an application release | Record matching source/image identifiers and complete the [release template](../../src/qc_tool/database/RELEASE_TEMPLATE.md) |
| Deploy or recover an installation | Follow the [deployment guide](../deployment/index.md) and [operations guide](../deployment/operations.md#upgrades) |

`database apply` supports an entirely empty production database. For a complete
schema matching the current models it performs a read-only no-op. It refuses
partial or foreign schemas and detected model drift; it never resets a database,
repairs existing tables or converts legacy records. An empty product catalog does not mean that
the database is empty.

Readiness inspection compares required managed tables, columns, backend types,
nullability, primary-key generation, foreign keys, uniqueness, named `Meta`
CHECK predicates and declared index definitions. It also checks SQLite JSON
validity. It does not exhaustively compare field-generated positive-integer
CHECKs, arbitrary additional constraints, triggers or privileges. Schema readiness
does not prove restored record completeness, account authorization or storage
availability; verify those against the handoff manifest and application workflows.

Legacy conversion and its source archives are private operator work outside the
maintained application. Restore a validated current-schema artifact into a
separate target; never restore legacy DDL over an application database.

The first migration definitions may be introduced only in a separately reviewed
3.0.1-or-later release. That future work must define an explicit transition for
existing databases; this branch supplies no migration or automatic adoption path.

Read the guide and commands from the same source revision as the pinned release
image. This page provides navigation; keep the implementation and procedure in
`src/qc_tool/database/` so they have one owner.
