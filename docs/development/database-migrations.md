---
title: Database migrations
parent: Development
nav_order: 5
---

# Database migrations

Start with the [QC Tool database guide](../../src/qc_tool/database/README.md)
and [choose the workflow](../../src/qc_tool/database/MIGRATIONS.md#choose-the-workflow)
for the release you are maintaining. The database package owns the policy,
schema initialization, future migration graph, deployment command, checks,
tests and runbook for the whole application. **3.0.0 is models-only (`draft`) and
contains no first-party migration definitions or baseline snapshots.** The first
migration-managed release may be 3.0.1 or later, after an explicit review.

| Task | Instructions |
| --- | --- |
| Change a model while the policy phase is `draft` | [Draft schema development](../../src/qc_tool/database/MIGRATIONS.md#draft-schema-development); change models without migration files |
| Validate a schema change before review | [Local verification](../../src/qc_tool/database/MIGRATIONS.md#local-verification) on disposable databases |
| Prepare 3.0.0 | Verify models on fresh targets and record the unresolved production initialization gate; do not generate migrations |
| Introduce migration history in 3.0.1 or later | [Reviewed freeze](../../src/qc_tool/database/MIGRATIONS.md#freeze-the-first-release) plus an explicit transition for existing databases |
| Change a schema after release freeze | [Author and review forward migrations](../../src/qc_tool/database/MIGRATIONS.md#development-after-the-major-release-is-frozen) |
| Prepare an application release | Complete the [release record](../../src/qc_tool/database/MIGRATIONS.md#release-record) using the [release template](../../src/qc_tool/database/RELEASE_TEMPLATE.md) |
| Deploy compatible PostgreSQL changes | [Online rollout sequence](../../src/qc_tool/database/MIGRATIONS.md#online-rollout-sequence) and the deployment's [operations guide](../deployment/operations.md#upgrades) |
| Investigate a failed migration or recover a release | [Failure and recovery](../../src/qc_tool/database/MIGRATIONS.md#failure-and-recovery) |

Existing 3.0.0 tables and data are not automatically adopted by new initial
migrations. Review a fresh-target conversion or separately approved adoption
design; do not use fake migration records or reset an occupied database.

For SQLite or incompatible schema changes after the future freeze, use the documented maintenance
workflow. A nearly zero downtime PostgreSQL migration also needs compatible
frontend and worker versions, staged data changes and suitable rollout
infrastructure; successful CI alone does not establish those conditions.

Read the canonical files from the **same source revision as the pinned release
image**. Check out that release tag or commit before following the procedures.
The relative links above stay within that source revision. This page is navigation;
maintain the procedure in `src/qc_tool/database/` so it has one owner.
