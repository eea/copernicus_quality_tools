---
title: Production readiness evidence
parent: Deployment
nav_order: 5
---

# Production readiness evidence

This records the 2026-10-21 maintenance, record-transfer and image hardening
checks. The delivery path is **reviewed commit → GitHub release tag → Docker Hub
automated builds → verified image pair → EEA deployment**. Local candidate builds
verify the code that will be packaged. Tag CI and Docker Hub run independently;
publishing images does not switch the EEA installation.
Follow the [deployment runbook](index.md) and record the actual installation with the
[release template](../../src/qc_tool/database/RELEASE_TEMPLATE.md).

## Changes verified by this review

| Boundary | Resulting behavior |
| --- | --- |
| Database selection | Unknown `DB_ENGINE` values stop configuration; a PostgreSQL typo cannot silently choose SQLite |
| Transfer admission | Admin shows concrete read-only schema diagnostics before enabling transfer controls; direct requests enforce the same preflight |
| Native restore destination | An explicit Admin action creates a unique empty database per import; no Compose change, reset, drop or overwrite is required |
| Activation and rollback | Verified native restore, current models, connected records/files and destination administrator access precede an explicit switch; maintenance stays on and same-window rollback retains both databases |
| Recovery after restart | A failed selected database can admit the recovery UI only with a verified retained database in the same ready maintenance generation; ordinary startup readiness remains enforced |
| Reviewed destination | Plans bind to the configured backend, database, host and port, and PostgreSQL's actual current database/schema |
| Recovery journals | Duplicate fields, non-finite numbers, malformed shapes/timestamps, unsafe locks and oversized journals fail closed; rejected journal writes preserve the prior journal |
| Cancel and discard | Committed/uncertain imports and unreconciled file publication cannot be cancelled, including after a recovery retry is queued; safe discard removes private package bytes and preserves audit journals |
| Maintenance drain | A streaming writer remains admitted through registered response cleanup, including iterator exhaustion/errors |
| Read-only browsing | Database-changing `SELECT INTO` and mutating SQLite PRAGMAs are rejected; audited SQLite introspection remains available |
| Production startup | Read-only schema verification precedes serving; demo credentials, development server and unsupported multi-process frontend settings are refused |
| Image provenance | Frontend and worker package the reviewed checkout; CI exercises packaged sources without a repository overlay; local backups are excluded from build context |
| Release identity | Tag pushes run CI; the build hook preserves the release tag as `VERSION` and records the source SHA separately in the OCI revision label |
| Service supervision | Production manifests require explicit image references, private networking, health dependencies and child reaping; replace a failed worker as a whole container |
| QC runtime | Unreadable vector sources abort cleanly; area overlaps remain visible; empty intersections cannot create marginal exceptions; raster mask extents use the mask origin |
| INSPIRE transport | Optional version lookup has a request timeout; result polling accounts for elapsed request time as well as waits |
| Validator startup | Supervisor receives configured Java heap/proxy arguments without shell evaluation or credential logging; quoted values retain their argument boundaries |

No first-party migrations, baseline snapshots, legacy converters or automatic
schema adoption were introduced. Original specifications and uploaded snapshots
remain unchanged.

## Verification

All database-writing checks use synthetic records and separate disposable
databases. The retained local installation was not reset, repaired, upgraded
or switched to another database.

| Check | Evidence |
| --- | --- |
| Frontend image | Built from the checkout on local Linux ARM64 with Python 3.12.14 and Django 5.2.17 |
| Packaged frontend regression suites | Final image ran 1,288 tests successfully on each backend: PostgreSQL (1 skip) and SQLite (9 skips), including transfer recovery and real API authentication regressions |
| JavaScript | 126 tests passed |
| Worker maintenance/auth/scheduler | 32 focused tests passed |
| Models-only source | 5 tests and source gate passed |
| Maintainer tooling | 24 tests passed after the tag-release follow-up, including build-hook metadata fallbacks, actual Supervisor execution and quoted Java argument regressions |
| Production security settings | `check --deploy --fail-level WARNING` passed with explicit HTTPS/proxy/HSTS settings and throwaway credentials |
| Real WSGI startup | Packaged production frontend started against a separate restored database; health/login and Secure/HttpOnly CSRF cookies passed with trusted-proxy HTTPS headers |
| Current-model PostgreSQL | Empty initialization, role bootstrap, synthetic connected records and read-only repeated `apply` passed |
| Native PostgreSQL recovery | `pg_dump --format custom`, restore into another empty database, schema check and all-table row fingerprints matched: 24 tables, 168 synthetic rows |
| Packaged worker QC suite | Exported Linux ARM64 image ran 382 tests successfully (9 external INSPIRE skips); runtime driver checks and `pip check` passed |
| Worker startup | Five entrypoint/actual-Supervisor tests passed inside the Python 3.12 image; supervised scratch PostgreSQL/scheduler startup and health HTTP 200 passed with INSPIRE disabled; real Java accepted the configured default heap arguments |
| Configuration | Three supported Compose profiles render; startup/build shell syntax checks passed |
| Tag release follow-up | Five offline hook tests passed for release tags, branch builds, metadata fallbacks and build paths; `actionlint`, build-hook shell syntax and `git diff --check` passed |

Native restore fingerprint:
`7c2a7d508af47aff309047fdb988d2babdcc2b23c83f1a05e898b13964690a4a`.
This fingerprint identifies this synthetic rehearsal only, not a production
backup. No images were published and no live production deployment was changed.

The subsequent UI restore/activation follow-up was verified against the current
checkout mounted in the local frontend runtime, without rebuilding or publishing
an image. Its final full SQLite run passed 1,427 tests (40 backend-specific skips),
all 127 JavaScript tests passed, and the broad PostgreSQL transfer/auth/Admin suite
passed all 322 tests. Real PostgreSQL checks exercised native
restore, current-model activation, unchanged source fingerprints and rollback.
An isolated HTTP rehearsal additionally exported a complete database, uploaded
it, prepared/restored its destination, switched, exported again as the retained
source administrator, and switched back. A second rehearsal made the selected
copy unavailable, restarted Gunicorn through the restricted recovery admission,
authenticated through both retained-source and stale SQL-cookie cases, and
rolled back through the UI. These rehearsals used disposable databases and
private temporary storage; the serving local selection remained unchanged.

Local Docker Desktop exported usable worker images, but its Buildx client stalled
after the export completed, including a retry without provenance generation.
The stalled clients were interrupted; packaged runtime checks use the exported
images. A clean worker build on the release CI runner remains required. Local
storage pressure also triggered transfer reserve refusals during a frontend
retest; both complete frontend suites passed again after reclaiming inspected
unused build cache. No transfer reserve checks were weakened.

The dependency review updated `urllib3` to 2.8.0 and replaces the unsupported
PyPDF2 parser with maintained `pypdf`. Upstream documents the relevant
[HTTP streaming issue](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw)
and [PDF parsing issue](https://github.com/py-pdf/pypdf/security/advisories/GHSA-4vvm-4w3v-6mr8).
Build tools are upgraded in the final worker environment as well. These changes
are checked with dependency validation and the affected runtime tests; this is
not a claim that every system dependency has been security-certified.

## Existing database cutover

An earlier v3 draft database missing `qc_database_transfer_receipt` is incompatible
with the current models. The new table supplies atomic import receipts; omitting
it or bypassing readiness would remove a recovery guarantee.

Under the [v3.0.0 database policy](../../src/qc_tool/database/README.md), `database
apply` initializes only an entirely empty database. It cannot add a missing table
to an occupied database. Portable Admin exports require a matching schema;
complete native PostgreSQL backups can preserve an older schema without altering
it. Activating a restored copy still requires current-model readiness.

For retained data, preserve a native PostgreSQL backup and matching files/secrets,
then prepare and verify a separate current-schema target through the reviewed
manual handoff procedure. Do not restore old DDL over a model-created target.
For a new installation, initialize a separate empty target explicitly and
provision accounts, specifications and boundaries before accepting QC work.

Future migration management begins with a separate reviewed v3.0.1-or-later
transition. The record-transfer reader refuses unknown model contracts rather
than guessing a conversion from a release version.

## Installation checks that remain operator responsibilities

Use the PostgreSQL profile for the intended installation with hundreds of users.
Measure the actual workload: the current supported topology has one frontend
process/container, multiple workers and persistent storage with reliable POSIX
locking, atomic publication and file/directory synchronization.

Before switching traffic, validate the exact image pair on the production CPU
architecture, real accepted/rejected QC inputs, bundled/external INSPIRE service,
S3 access when used, product access and publication retention. Confirm public
HTTPS routing, host/origin policy and proxy header ownership. Liveness alone
does not certify database compatibility or maintenance readiness.

Configure reverse-proxy body limits, request timeouts and temporary upload space
for the chosen package sizes. Multipart uploads may occupy temporary storage
before application archive limits are checked; `QC_TOOL_UPLOAD_TEMP_DIR` selects
a preprovisioned private directory. Budget for compressed packages, expanded
files, journals and reserve space together. Keep transfer files outside public
static/media paths and monitor capacity and recovery-required operations.

Native SQL inventory streams table data, and native activation is independent
of the portable package record limit. Current application graph validation still
materializes the connected records in memory, and review hashes every retained
local file. Measure memory, review duration and proxy/Gunicorn timeouts with the
installation's real dataset. An interrupted preflight leaves the active pointer
unchanged; this is not a claim that arbitrarily large installations have been
load-tested.

Rehearse restore using a real current backup and its matching storage, verify
record/file checksums and application access, and record the recovery duration.
Application maintenance fences participating writers; stop services and close
readers before DDL or replacing a database. Never resume by deleting a pin or
editing authority/journal files.
