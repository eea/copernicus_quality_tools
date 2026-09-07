---
title: Database migrations
parent: Development
nav_order: 5
---

# Database migrations

Start with the [QC Tool database guide](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/README.md)
and [choose the workflow](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#choose-the-workflow)
for the release you are maintaining. The database package owns the policy,
complete migration graph, deployment command, checks, tests and runbook for the
whole application.

| Task | Instructions |
| --- | --- |
| Change a model while the policy phase is `draft` | [Draft schema development](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#draft-schema-development); change models without migration files |
| Validate a schema change before review | [Local verification](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#local-verification) on disposable databases |
| Prepare the first major release | [Explicit release freeze](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#freeze-the-first-release), then [manual production cutover](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#one-time-manual-production-cutover) into a new database |
| Change a schema after release freeze | [Author and review forward migrations](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#development-after-the-major-release-is-frozen) |
| Prepare an application release | Complete the [release record](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#release-record) using the [release template](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/RELEASE_TEMPLATE.md) |
| Deploy compatible PostgreSQL changes | [Online rollout sequence](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#online-rollout-sequence) and the deployment's [operations guide](../deployment/operations.md#upgrades) |
| Investigate a failed migration or recover a release | [Failure and recovery](https://github.com/eea/copernicus_quality_tools/blob/dev/src/qc_tool/database/MIGRATIONS.md#failure-and-recovery) |

For SQLite or incompatible schema changes, use the documented maintenance
workflow. A nearly zero downtime PostgreSQL migration also needs compatible
frontend and worker versions, staged data changes and suitable rollout
infrastructure; successful CI alone does not establish those conditions.

Read the canonical files from the **same source revision as the pinned release
image**. The links above open the development branch; use the release tag or
commit in GitHub when operating a released version. This page is navigation;
maintain the procedure in `src/qc_tool/database/` so it has one owner.
