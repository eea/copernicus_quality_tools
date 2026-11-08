# QC Tool installation and upgrade record: <version>

Record the exact release, database copy and storage before production installation.
Store credential references, never secret values. Follow the [migration runbook](MIGRATIONS.md)
and [manual restore guide](MANUAL_RESTORE.md).

## Release and recovery identity

| Item | Value |
| --- | --- |
| Operator and maintenance window | |
| Source release, commit, schema contract and migration history | |
| Target release, commit and reviewed graph/hash | |
| Matching frontend/worker immutable image digests | |
| PostgreSQL server/client major and source/candidate OIDs | |
| Maintenance generation and selection revision | |
| Archive SHA-256, selected/omitted sections and original restore evidence | |
| Source dates, provenance and missing/external content | |
| Storage identities, checksums and retention pins | |
| Private configuration/credentials/globals recovery references | |
| Independent off-host backup and restore rehearsal | |
| Previous images/database and compatible or offline recovery procedure | |

## Verification gates

- [ ] Source schema/history matches its explicit supported contract.
- [ ] Target migrations are committed, reviewed and unchanged.
- [ ] Maintenance is ready; workers acknowledged and external writers isolated.
- [ ] Backup covers SQL and retained files; omissions/remote/private requirements are explicit.
- [ ] Checksum and exact original restoration verify in a separate owned candidate.
- [ ] Initial adoption, if needed, affects only that strictly verified candidate.
- [ ] Native migrations complete; target schema/history and administrator access verify.
- [ ] IDs, passwords, tokens, ownership, timestamps, FKs, sequences and business history reconcile.
- [ ] Original specifications, ZIPs, boundaries, results and publications retain identities and verified bytes.
- [ ] Explicit switch retains previous database, backup, journals and file pins.
- [ ] Login, denied/allowed access, upload, QC, publication, review and readiness pass with the exact images.
- [ ] Recovery and the point where quick rollback expires are understood.
- [ ] Operator authorizes reopening and monitors the selected target.

## Ordered evidence

| Order | Action | Expected result | Actual evidence |
| --- | --- | --- | --- |
| 1 | Rehearse supported source → target on a disposable copy | | |
| 2 | Verify images, storage, capacity and maintenance | | |
| 3 | Create and independently retain coordinated backup | | |
| 4 | Restore and verify a separate candidate | | |
| 5 | Apply installed migrations; verify schema/files/access | | |
| 6 | Explicitly select candidate with recovery assets retained | | |
| 7 | Verify workflows, reopen and monitor | | |

Stop on failed prerequisites. Never reset, repair or fake history on an occupied
production/developer database. Retain uncertain candidates and evidence after lost
acknowledgements. Across incompatible schemas, recover with previous images and
retained data offline. Reverse migrations cannot reconstruct discarded data/files.
