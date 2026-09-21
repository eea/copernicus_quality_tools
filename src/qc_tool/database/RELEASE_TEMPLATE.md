# QC Tool release record: <version>

Copy this template into the release PR or your deployment records. Complete it
before deployment, then attach the actual results. Use `not applicable` with a
reason where appropriate. Store secret references, never secret values. The
[migration runbook](MIGRATIONS.md) defines the procedure; this record captures the
decisions and evidence for one release. It is not another executable manifest.

## Release identity

| Item | Value |
| --- | --- |
| Owner and operator | |
| Release version and source commit SHA | |
| Previous release and supported upgrade starting points | |
| Policy phase (`released` for production) | |
| Frontend image digest | |
| Worker image digest and compatibility evidence | |
| Target environment, Compose project/config revision | |
| Database engine/version, host and database name (no credentials) | |
| Shared storage identities | |
| CI runs and artifact smoke-test results | |

## Change and compatibility

- Release behavior and affected workflows:
- Migration identities from `database plan`, across all apps (or no changes):
- Path: empty installation / manual legacy cutover / PostgreSQL expansion /
  backfill or reader switch / later contraction / maintenance upgrade:
- What the old frontend and workers can read/write after the schema change:
- What the new frontend and workers require before starting:
- Queued/running jobs, clients and background tasks affected:
- Transaction behavior, expected duration, lock/statement timeout bounds:
- Data-preservation and authorization assertions:
- Schema operations deliberately deferred to a later release:

## Rehearsal and recovery

- Starting release, isolated database/storage snapshot and representative volume:
- Baseline verification and migration-specific predecessor tests:
- Old/new application and worker smoke tests:
- Measured lock wait, migration/backfill duration, load and replication impact:
- Backup identifiers, restore rehearsal result, recovery time/data-loss limits:
- Latest point at which application images alone can be rolled back:
- Action if DDL partly commits or concurrent index creation fails:
- Action if a backfill stops, including checkpoint and safe resume command:
- Restore or forward-repair procedure, including writes since the backup:

## Ordered deployment steps

Write the **exact commands and expected result** for this environment. Include
the pinned Compose configuration and environment-lock owner. Every step needs
an explicit stop condition; a failed migration must block service rollout.

| Order | Action/command | Expected result | Stop/recovery condition | Actual result/time |
| --- | --- | --- | --- | --- |
| 1 | Verify target and images; acquire environment lock | | | |
| 2 | Establish traffic/job handling and backup evidence | | | |
| 3 | Plan, then apply schema once with restricted diagnostic logs | | | |
| 4 | Check migration state and validate data | | | |
| 5 | Deploy compatible frontend/workers and verify health | | | |
| 6 | Run/schedule backfill or manual import at its required stage | | | |
| 7 | Resume/switch traffic and monitor | | | |

Reorder the template steps for the selected path: manual import happens before
new services start; an online backfill happens after compatible writers are
deployed. Supply import mappings or backfill commands, dry-run results,
batch/checkpoint settings and completion assertions where applicable.

## Acceptance and follow-up

- Login/logout and static assets:
- Allowed **and denied** user/product access:
- Upload, delivery/job state and representative worker execution:
- Catalog/product unit provenance and submission/filesystem consistency:
- Empty-installation catalog remains empty until administrator upload or explicit reviewed import:
- Migration state current; data assertions and backfill completeness:
- Error rate, latency, queue age and database load within recorded limits:
- Migration/deployment log location and operator decision:
- Rollback window end and retained recovery assets:
- Owner and earliest eligible release for contract/cleanup work:
