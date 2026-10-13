# QC Tool installation record: <version>

Record evidence for the exact database copy and application images before manual
production installation. Store credential references, never secret values.
See [initialization](MIGRATIONS.md) and [manual restore](MANUAL_RESTORE.md).
v3.0.0 has no migration history or upgrade machinery.

## Identity and source

| Item | Value |
| --- | --- |
| Owner/operator and planned cutover time | |
| Version and source commit | |
| Frontend/worker immutable image digests | |
| Target PostgreSQL version and new database identity | |
| Archive filename, SHA-256 and restore evidence | |
| Source capture dates, provenance and known omissions | |
| Shared storage backup identities | |
| Recovery copy and traffic-switch rollback procedure | |

## Verification

- [ ] Restore archive into an entirely empty isolated target; checksum matches.
- [ ] `database check` passes with the selected source/image in production mode.
- [ ] IDs, ownership, timestamps, record counts, foreign keys and sequences match.
- [ ] Historical submitted filenames reject duplicate admission, including case changes.
- [ ] Account passwords and permitted product access are explicitly provisioned.
- [ ] Original specifications/catalog and shared input/report/submission files are available.
- [ ] Credentials, boundary storage and active worker configuration are verified.
- [ ] Login, denied/allowed access, new upload, QC, publication and review are verified.
- [ ] Same-input QC pass/fail agrees with production, except damaged ZIPs.
- [ ] Source writes/workers and target traffic have a coordinated cutover plan.

## Ordered manual installation

| Order | Exact command/action | Expected result | Actual evidence |
| --- | --- | --- | --- |
| 1 | Verify target identity, recovery assets and source-write handling | | |
| 2 | Restore into a new empty target, or initialize a completely new installation | | |
| 3 | Check schema and reconcile data/files/access | | |
| 4 | Start the compatible frontend and workers | | |
| 5 | Run workflow checks and switch traffic | | |
| 6 | Monitor and retain recovery copy | | |

Stop on any failed prerequisite. Existing databases are never reset, faked or
repaired by the initializer. No production action is implied by preparing this
record or a private local database copy.
