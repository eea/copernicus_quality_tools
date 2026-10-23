---
title: Maintenance architecture research
parent: Architecture
nav_order: 8
---

# Maintenance architecture research

This report records the repository research behind administrator-controlled
maintenance mode on 20 October 2026. It distinguishes the behavior found before
this feature from the maintenance contract the application must enforce. It is
source research, not an audit of the live EEA installation, its registry,
production infrastructure or backup provider.

The application can close writer admission and interrupt its own work while
authorized users continue reading existing data. That establishes an application
maintenance barrier for writes. It cannot grant an exclusive
database lock against other SQL clients, deployment jobs or administrators.
Physical backup and schema work still require the operator's database/storage
procedure and the version's supported database policy.

## 1. Application boundaries and ownership

| Component | Responsibility | Persistence and dependencies | Source |
| --- | --- | --- | --- |
| Django frontend | Browser UI, API, accounts, catalog, delivery admission, queue claims, publication and administration | One application SQLite or PostgreSQL database; shared input, work, boundary, specification and publication storage | [settings](../../src/qc_tool/frontend/settings.py), [root URLs](../../src/qc_tool/frontend/urls.py), [dashboard models](../../src/qc_tool/frontend/dashboard/models.py) |
| Accounts | Identity, roles, permissions, product scope and personal API credentials | Django account/session tables and account-owned models | [accounts architecture](authentication-and-authorization.md), [API authentication](../../src/qc_tool/frontend/accounts/authentication/api_keys.py) |
| Dashboard domain and services | Delivery/job history, catalog versions, product units, submissions and file/database coordination | Application DB plus durable files; services own locking and invariants | [repository layout](repository-layout.md), [data flow](data-and-job-flow.md) |
| Worker scheduler | Polls frontend, limits local concurrency, tracks job controllers and exposes authenticated status | In-memory job table; scheduler logs and token on shared work storage | [scheduler](../../src/qc_tool/worker/scheduler.py), [worker authentication](../../src/qc_tool/worker_auth/) |
| Worker command and dispatcher | Validates job arguments, materializes input, executes configured checks and writes result/PDF/attachments | Shared inputs/work plus worker-local scratch and QC SQL database | [command](../../src/qc_tool/worker/cmd.py), [dispatcher](../../src/qc_tool/worker/dispatch.py), [managers](../../src/qc_tool/worker/manager.py) |
| Worker infrastructure | PostGIS, GDAL, validator, Java, proxy and service supervision | Embedded PostgreSQL 17/PostGIS is QC scratch, separate from the frontend database | [worker image](../../docker/Dockerfile.worker), [Supervisor](../../docker/supervisord.conf) |
| Central database package | Models-only schema initialization and readiness for the whole application | Accounts, dashboard and Django framework tables together | [database ownership](../../src/qc_tool/database/README.md), [policy](../../src/qc_tool/database/policy.json) |

Accounts supplies identity/capability facts; dashboard access policies combine
those with ownership and product scope. A maintenance controller should reuse
that authorization contract and Django Admin's session/CSRF boundaries. It should
not place delivery/job knowledge in accounts, embed maintenance behavior in
raster/vector checks, or modify specifications.

Frontend and worker coordinate through authenticated HTTP and common file
storage. Workers normally do not write the frontend application database
directly. That distinction matters: stopping a worker prevents result-file and
QC scratch writes; suppressing frontend refresh prevents result facts from
being persisted into the application database.

## 2. Job lifecycle and places that can still write

1. A browser uploads bounded resumable chunks. Finalization publishes a complete
   ZIP and registers a Delivery with durable retry/overwrite records. API S3
   registration stores location metadata and a private credential reference.
2. A browser/API request creates a waiting Job under a Delivery row lock,
   snapshots the authoritative specification/release and updates Delivery's
   latest-job projection.
3. A worker polls `POST /pull_job` using the shared WorkerToken. A guarded
   `waiting` to `running` update chooses a single claimant and records its
   worker URL and start time.
4. A local controller starts `/usr/bin/time python3 -m qc_tool.worker.cmd`.
   The dispatcher pins one immutable boundary generation and invokes the
   specification's configured steps. External tools and SQL can run beneath
   this process.
5. The dispatcher stores incremental/final JSON, attachments and a PDF on work
   storage. The QC connection manager creates a per-job scratch schema in the
   worker's SQL database; normal context cleanup drops it unless retention was
   explicitly enabled.
6. Frontend status polling checks worker liveness/result files, persists terminal
   Job metadata and synchronizes the Delivery projection. Both an HTTP polling
   route and a WSGI background thread can trigger that persistence.
7. Publication reserves and copies deliverables and writes retained receipts;
   review, release acceptance, deletion, product administration and user changes
   have additional write paths.

Sources: [upload/job flow](data-and-job-flow.md), [job creation](../../src/qc_tool/frontend/dashboard/services/product_units/jobs/creation.py),
[claim](../../src/qc_tool/frontend/dashboard/domain/jobs/queue.py),
[worker pull endpoint](../../src/qc_tool/frontend/dashboard/views/workers.py),
[dispatcher](../../src/qc_tool/worker/dispatch.py),
[status refresh](../../src/qc_tool/frontend/dashboard/views/jobs/status.py),
[terminal persistence](../../src/qc_tool/frontend/dashboard/services/product_units/jobs/completion.py),
[WSGI entrypoint](../../src/qc_tool/frontend/wsgi.py).

Maintenance must therefore cover more than upload POST requests:

| Writer | Required maintenance behavior |
| --- | --- |
| Requests already executing when the switch is pressed | Finish admission-controlled work before reporting quiescence; do not assume changing a boolean stops a request already in progress |
| New browser/API uploads, finalization, replacements and S3 registration | Refuse admission without consuming/activating new data |
| New QC requests and worker queue claims | Refuse new work atomically with the transition |
| Already waiting jobs | Preserve history and explicitly stop/cancel or hold them; never let them start behind the maintenance barrier |
| Running worker jobs and descendant commands | Interrupt, wait for confirmed exit and only then reconcile frontend state |
| WSGI refresh and HTTP status refresh | Stop background mutations once transition/reconciliation completes |
| Admin catalog, users, grants, review and publication actions | Block ordinary mutations during the maintenance window; broad `/admin/` exemption is insufficient |
| Authentication side effects | Block login/logout and account mutations; use read-only sessions and suppress API token-use updates for authorized browsing |
| Deployment tasks, shell commands and external SQL/storage clients | Outside the UI's enforcement boundary; coordinate/stop separately |

Read-only browsing is admitted separately after the writer fence closes. Existing
browser sessions and API credentials retain normal account/product/ownership
checks. Session persistence, API token-use updates and history/status refresh
writes are suppressed; login/logout and other account mutations remain blocked.
An ORM write guard rejects unexpected writes in read requests. New readers do
not hold the writer barrier, so they do not prevent writer/worker readiness.

The existing job-history rule remains: individual jobs are retained logs.
Stopping a job does not authorize deleting its Job, Delivery, input ZIP, published
submission or specification snapshot. A maintenance interruption must have a
clear terminal status and finish time, preserve provenance and avoid projecting
a cancelled run as a successful QC result.

## 3. Deployment profiles

| Profile | Frontend DB | Durable layout | Runtime source/model | Operational implications |
| --- | --- | --- | --- | --- |
| [Service provider](../../docker/docker-compose.service_provider.yml) | SQLite at `FRONTEND_DB_PATH` | One named `qc_tool_volume` for DB, boundaries, incoming and work; submission disabled by default | Published frontend/worker images | Single frontend writer; coordinate SQLite and shared files for a consistent backup |
| [EEA baseline](../../docker/docker-compose.eea.yml) | Separate PostgreSQL 14 `userdb` | Separate PostgreSQL, boundary, incoming, work and submission volumes | Published frontend/worker images | Keep DB plus every referenced durable volume together; supplied manifest is a baseline to customize |
| [Local](../../docker/compose.local.yaml) | PostgreSQL 14 with loopback-only host port | Separate named volumes, including frontend static storage | Locally built matching frontend/worker runtimes, current checkout mounted read-only into both | Development initialization/demo users explicitly enabled; existing DB must not be reset after model drift |

Production profiles require explicit `QC_TOOL_FRONTEND_IMAGE` and
`QC_TOOL_WORKER_IMAGE` references; they no longer default to legacy release
candidates. Both Dockerfiles package the reviewed checkout from the repository
root rather than fetching a source archive. The local profile builds both
runtimes; current source over a legacy Python 3.8 worker is unsupported.

The frontend production entrypoint rejects the old migration-startup option,
runs a read-only database readiness check, collects static assets and starts
Gunicorn. Automatic empty-database initialization and predictable demo accounts
are allowed only in explicit development/test settings. The default is one
Gunicorn worker because importing WSGI starts a status-refresh thread. Current
deployment guidance also requires one frontend container. Multiple worker
replicas can claim the same queue safely.

The worker runs a Bottle control/status service and scheduler under Supervisor,
alongside optional PostgreSQL, validator and proxy components. It needs shared
storage with the frontend. The shared WorkerToken protects internal job/status
requests; the public `/health` route contains no job data. Production baselines
expose frontend port 8000 and need an external trusted HTTPS ingress.

Sources: [frontend entrypoint](../../docker/run_frontend.sh),
[WSGI](../../src/qc_tool/frontend/wsgi.py), [Supervisor](../../docker/supervisord.conf),
[deployment guide](../deployment/index.md), [operations](../deployment/operations.md),
[environment reference](../reference/environment-variables.md).

Maintenance state and any cooperation locks must reside on durable storage
visible to every cooperating frontend/worker, with consistent paths and file
locking/atomic-rename semantics. Container-local memory or a container-local
file would lose the barrier on restart. A database-only maintenance flag creates
an additional dependency during schema work, while file-backed configuration
can reuse the application's existing safe configuration-storage conventions.
This does not expand current frontend scaling support.

## 4. CI, image construction and release delivery

The checked-in [GitHub Actions workflow](../../.github/workflows/integration-tests.yml)
is named **QC Tool integration tests**. It runs on pushes to `dev` and
`release/**`, all tag pushes, and pull requests targeting `dev` or `release/**`.
Its token has read-only contents permission, and a new run cancels the previous
run for the same ref.

| Job/gate | What it verifies | Important limits |
| --- | --- | --- |
| Maintainer tools | Python 3.12 offline evidence-runner tests | No real QC, production DB or deployment |
| Frontend matrix | Separate SQLite and PostgreSQL 14 runs; PostgreSQL service has a health check | Disposable synthetic databases |
| Browser upload tests | Node.js 22 component/adapter event tests | No full browser or live production interaction |
| Source contract | Database source tests and models-only source gate | Deliberately rejects first-party migration history/converters |
| Runtime build | Builds frontend and worker from the proposed checkout | CI tests packaged source without overlaying a different checkout |
| Schema/runtime | Python/Django pin assertions, disposable schema checks, Django checks, readiness and static collection | Schema readiness is not a production record/storage reconciliation |
| Regression suite | Accounts, dashboard services/views, database integration and uploaded-definition tests | Worker scheduler/process termination requires explicit additional test labels; the frontend package labels do not discover it |
| Production settings | Throwaway production-mode `check --deploy --fail-level WARNING` and Compose validation | No external TLS proxy or infrastructure certification |

The **Worker admission and interruption** CI job exercises explicit
scheduler/protocol/process-group test labels. The frontend matrix discovers the
Admin, service and readiness tests. The separate **Supported worker image and QC
regressions** job builds the full Python 3.12 geospatial image, validates runtime
imports/drivers and `pip check`, and runs the synthetic worker QC suite against a
disposable embedded scratch PostgreSQL with external INSPIRE calls disabled.
These are gates to run, not proof of live external services or customer-file QC
acceptance parity.

The frontend image pins its Python base/digest and Python dependency graph.
Both image builds require `VERSION` as the displayed release version and package
the source checkout. `SOURCE_REVISION` records the commit SHA separately in the
OCI revision label. The Docker Hub hook uses `SOURCE_BRANCH` for the release tag
and `SOURCE_COMMIT` for its revision.
The worker uses pinned Ubuntu 24.04 with Python 3.12 in a private virtual
environment, retained GDAL 3.8.4/Arrow 17/Java 11/PostgreSQL 17 components and
checksum-verified infrastructure/source downloads. OS repositories and remaining
Python transitive resolution still require image inventory/scanning and recorded
image digests; a Dockerfile alone does not establish complete reproducibility.

There is no checked-in production deployment, registry-push, release approval,
environment lock, automatic rollback or scheduled backup workflow under
`.github/workflows/`. The operator confirms that GitHub release tags trigger the
existing Docker Hub automated builds for both images. The private Docker Hub
build rules and EEA deployment settings were not independently inspected. GitHub
Actions and Docker Hub run independently; tag CI does not gate Hub publication.
Tag a reviewed, already-green commit, verify both published images, then hand
their digests to EEA. See [Docker Hub images](../deployment/dockerhub-images.md).
Do not infer automated server deployment from successful tests or
`docker compose pull`.

The supported release procedure is operator-driven: pin matching images,
render and inspect the deployment configuration, allocate/validate the target,
coordinate maintenance and backup, stop writers, verify the selected schema and
retained storage, recreate services, exercise access and representative QC,
then reopen service. A deployment runner must serialize concurrent deployments.

Sources: [frontend image](../../docker/Dockerfile.frontend),
[frontend requirements](../../docker/requirements.frontend.txt),
[worker image](../../docker/Dockerfile.worker),
[testing contract](../development/testing.md), [upgrade runbook](../deployment/operations.md#upgrades).

## 5. Gap in the previous maintenance implementation

Before this feature, `MAINTENANCE_MODE=yes` was loaded from environment into
Django settings. Middleware returned HTTP 503 for every application path except
`/admin/`, with no live UI switch. It did not stop already running requests,
the WSGI refresh loop or existing worker processes. It blocked new `/pull_job`
requests but had no interruption/acknowledgement protocol. Generic Admin writes
remained possible. It therefore reduced traffic but did not establish backup
readiness.

The original scheduler had authenticated job/table inspection and slot controls,
but no job cancellation route. Job controllers waited for a `Popen` child and
removed it from an in-memory table on exit; no process-group ownership or
descendant shutdown was tracked. Dispatcher exception/finalization and scratch
cleanup covered normal Python exits, not all OS-level interruption cases.

The reusable building blocks are the existing Admin authorization/CSRF support,
WorkerToken authentication, safe worker-origin validation, bounded machine JSON
contracts, domain job completion/projection services, shared storage, and safe
atomic file-backed configuration patterns. A new broker, Kubernetes control
plane, replacement QC engine or separate migration framework is unnecessary for
this feature.

## 6. Maintenance contract and failure handling

The selected design keeps maintenance state in shared `WORK_DIR`, outside the
application database. Atomic JSON state records the enabled flag, transition
generation and known worker origins; POSIX file locks serialize controller
actions and provide admission barriers for cooperating HTTP/background writers.
This avoids adding tables or migration machinery merely to control a schema
maintenance window. Every participant must use the same persistent storage;
its driver must implement cross-process `flock` and atomic replacement correctly.

Storage initializes OFF only when the application exclusively creates a new
maintenance directory. Existing-directory state loss fails closed even when no
other files remain. Strict bounded/versioned JSON validation, no-follow regular
lock files and safe regular-file reads protect the control state; reads do not
rewrite recognized older state formats. A failed bootstrap leaves an existing
directory requiring offline recovery rather than a second automatic reset.
Deletion of the entire directory or replacement of its volume remains a trusted
operator boundary: an empty storage allocation contains no evidence of an older
deployment and cannot safely be treated as a recovery action.

The dedicated maintenance control at `/admin/maintenance/` remains available to
an authorized administrator. Ordinary authorized Admin/application pages,
downloads and exports can also be browsed read-only. The UI shows a maintenance
notification and disables mutating controls; the server admission policy rejects
ordinary writes even if a client bypasses those controls. Existing sessions are
read-only and API authentication skips token-use persistence. Login/logout and
account mutations are blocked; the login page remains visible with sign-in
disabled. A management-command recovery path is needed if the administrator's
session expires.

The controller records worker origins seen through the ordinary authenticated
worker protocol. Every registered worker must acknowledge a matching-generation
pause and an empty active-work set before readiness. An unreachable or old
worker leaves maintenance enabled and readiness unconfirmed; a missing reply is
not evidence that work exited. A serial control lock and transition generation
prevent a late command from an older transition reopening or pausing workers
after a newer administrator action.

The maintenance service owns enable, readiness, disable and verified worker
retirement. The Admin view and management command are adapters to that public
service rather than independent places for database/registry mutations. A
[dedicated worker transport](../../src/qc_tool/frontend/dashboard/services/maintenance/workers.py)
owns authenticated HTTP and origin validation; bounded parallel probing belongs
to the controller. A [shared pure-Python protocol](../../src/qc_tool/maintenance/protocol.py) owns strict payload
validation without importing Django or the worker runtime. This keeps message
rules consistent and lets transport, lifecycle and adapters be tested separately.

One readiness check probes at most eight workers concurrently with a ten-second
worker-probing budget. Timeouts, pending probes and malformed replies remain
blockers. This bounds network coordination as worker counts grow instead of
holding a web request for five seconds per unreachable historical address.
Final job reconciliation still uses the existing transaction/Delivery-lock
services; the probe budget does not certify database-operation latency.

The controller's executor timeout bounds its wait; it does not cancel a running
socket operation. Executor shutdown uses `wait=False, cancel_futures=True` to
cancel unstarted work, while the worker transport enforces its own wall deadline
by shutting down the request socket. This follows the distinction between
pending and running calls in the official [Python 3.12 executor contract](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.Executor.shutdown).

The controller records `readiness_checked_at` only after positive confirmation;
the Admin page shows that observation separately from the enabled-state change
time. Rechecking invalidates the previous ready observation while it establishes
new evidence. Operator `on` and `check` return a nonzero exit status if they end
in stopping, allowing backup automation to require actual readiness. A readable
status command alone is not permission for a backup.

The admission middleware and control-session handling share [one classification](../../src/qc_tool/frontend/dashboard/access/maintenance.py)
of named routes and audited read semantics, evaluated against application-relative `path_info`.
This avoids duplicated literal-path exceptions and preserves behavior when the
application is mounted under a deployment URL prefix. The health route remains
separate from application/schema readiness.

Requests admitted before the transition retain the activity barrier through
stream iteration and release it on completion or close, including a response
closed before iteration starts. New read-only streams during maintenance do not
hold that writer barrier and do not postpone readiness.
The middleware assigns a closable iterator through public `streaming_content`
rather than consuming the stream or modifying Django's private closer list.
Wrapping the stream without reading it eagerly follows Django 5.2's documented
[streaming middleware contract](https://docs.djangoproject.com/en/5.2/topics/http/middleware/#dealing-with-streaming-responses).

Worker claim loops bound each batch by slots and a polling deadline, including
continuous short-job load. Fatal scheduler failures close local admission,
request interruption of owned controllers and make worker health unhealthy.
An HTTP server still answering after its scheduler failed must not advertise a
healthy worker. The matching frontend/worker protocol remains fail closed on
missing or incompatible authority responses.

After all workers confirm quiescence, waiting/running jobs are ended through the
existing terminal job/projection services with an error outcome and preserved
history. Interrupted work is not automatically resumed on disable. A forced
`MAINTENANCE_MODE=yes` remains recognized only for compatibility with older
custom deployments and cannot be overridden off by the UI. Current Docker
manifests omit that variable: the UI and `maintenance` command operate the same
persistent state without an environment change or container restart.

The administrator needs a dedicated Admin control displaying at least enabled
state, transition progress, active work and a concrete reason when quiescence
cannot be confirmed. Enabling maintenance should immediately close admission,
wait for already admitted writes, stop queued/running work through the existing
domain/worker boundaries, and report readiness only after acknowledgement.
Disabling should be an explicit authenticated CSRF-protected action and should
not silently retry interrupted jobs.

Required semantics:

- Persist the barrier before waiting for work to finish; a slow/unreachable
  worker must not leave new uploads or queue claims open.
- Serialize the transition with cooperating requests/refresh/claims. A check
  followed later by an unrelated write has an admission race.
- Cover active process trees, including long-running child commands. Reap owned
  processes and use a bounded graceful wait/escalation policy. Do not consider
  a Job status update proof that its worker stopped.
- Keep job identity, audit provenance and file ownership intact; reconcile
  terminal job state only when shutdown is confirmed. Never fabricate QC
  success or reuse old successful results for interrupted work.
- Treat unreachable workers, invalid control responses, unsupported worker
  versions, unsafe/malformed state and missing required shared storage as
  unresolved conditions. Preserve the barrier and explain the next action.
- Block ordinary Admin mutations while keeping the dedicated control reachable.
  Allow authorized Admin/application reads with read-only sessions, skip token-use
  and status/history persistence, and retain normal permission/ownership/CSRF
  checks. Login/logout and account writes remain outside read-only browsing.
- Classify routes by effect rather than HTTP method alone. Audited POST reads
  are table export, upload duplicate inspection and persisted job polling.
  Resumable-upload GET probes remain blocked because creating their lock files
  mutates shared storage. Unknown/unclassified effects fail closed.
- Distinguish process exit from remote-service cancellation. Work already
  submitted to an external validator may require separate service cleanup;
  it must not be represented as proof of a global infrastructure freeze.
- Retain partial uploads and safe recoverable artifacts for normal retry or
  deliberate operator cleanup. Forced exits may leave worker scratch schemas
  or temporary directories; avoid deleting unknown state automatically.
- Keep the environment override useful for emergency closure, with clear
  precedence if it forces maintenance on. An Admin switch cannot rewrite the
  environment of an existing container.

Acceptance evidence should cover unauthenticated/non-admin/administrator access,
CSRF, uploads and API rejection, claims racing the switch, an in-flight writer,
background refresh, queued and running job history, process-tree termination,
worker failure/timeouts, repeated enable/disable, restart persistence and
readiness that stays false when termination is unconfirmed. Run relevant worker
tests explicitly in CI; the existing frontend matrix does not discover them.
Read-only browsing adds SQL-write and filesystem-inventory assertions for allowed
routes, valid/invalid/expired sessions and tokens, safe POST read CSRF, Admin lazy
content-type behavior, disabled controls and new read streams that do not hold
the writer barrier. Its test matrix is in the [testing guide](../development/testing.md#read-only-maintenance-matrix).

The implemented controller, request/session middleware and operator commands
are documented in the [maintenance runbook](../deployment/maintenance.md).

## 7. Backup and schema-operation boundary

The backup unit is the application DB plus referenced durable storage:
`INCOMING_DIR`, `WORK_DIR`, boundary generations/current pointer,
`SUBMISSION_DIR` when enabled, S3 credential storage when separate, and original
uploaded specification storage/configuration. Inventory the effective deployed
paths and external mounts rather than relying only on default Compose names.
Protect credentials and restore file ownership/modes. A database dump cannot
recreate missing uploads, reports, specifications, S3 secrets or publications.

An operator should enable maintenance, wait for the verified barrier, stop any
additional deployment/session-cleanup/SQL writers, and take a coordinated
database/filesystem snapshot. PostgreSQL supports logical `pg_dump` archives;
SQLite needs its supported backup/snapshot mechanism or quiescent copying.
Verify checksums/inventory and rehearse restore into a new target. Resume only
after schema, retained records, file correspondence, credentials and the exact
frontend/worker pair have been validated.

For a full schema operation, the existing runbook still stops frontend and
workers and closes readers after entering maintenance. Ready means writers and
workers stopped while authorized readers may still use database connections.
The UI is an admission/interruption control,
not an online schema-management engine. A UI that remains connected to tables
while those tables are being replaced cannot prove that the schema is safe to
change.

The governing [v3.0.0 policy](../../src/qc_tool/database/policy.json) remains
`draft` with no baselines. Current models initialize an entirely empty database
through `database apply`; matching schemas are read-only no-ops and partial,
foreign or outdated schemas are refused. Maintenance does not change that rule,
make an occupied database empty, or authorize reset/repair/adoption. New schema
requires a separate fresh target and reviewed manual transfer. Initial managed
migrations belong to a separately reviewed v3.0.1-or-later policy transition.

Sources: [backup/upgrade operations](../deployment/operations.md),
[database contract](../../src/qc_tool/database/README.md),
[initialization runbook](../../src/qc_tool/database/MIGRATIONS.md),
[manual restore](../../src/qc_tool/database/MANUAL_RESTORE.md),
[publication retention](../../src/qc_tool/database/SCHEMA.md#retaining-verified-deliverables),
[product specification rules](../../AGENTS.md).

## 8. Evidence limits and operational follow-up

This research inspected repository source/manifests/docs. It did not connect to
production, verify image registry contents, execute a backup, restore customer
data, measure interruption latency under real QC load, or inspect external CI/CD
configuration. Files under `docker/docker_compose_examples/` are historical
examples and are not the supported production matrix above.

Before production rollout, rehearse a long-running real QC interruption in an
isolated environment, verify the actual volume driver's locking semantics,
publish matching images, validate restore and recovery controls, and record the
deployment's external writers and runner lock. Maintenance readiness is bounded
by those cooperating processes; database-level exclusivity remains an operator
responsibility.

Remaining priorities, separate from the implemented maintenance hardening:

1. **Validate and publish the supported worker image before release.** The
   historical local `2.4.6` image ran Python 3.8.10 despite the application's
   Python 3.11 minimum. Docker builds now use Ubuntu 24.04/Python 3.12 and retain
   the reviewed geospatial services; runtime checks reject old Python and missing
   required drivers. Build/test the exact final image pair, scan and record its
   inventory/digests, then rehearse actual QC interruption and recovery. The
   lightweight control tests alone do not certify the rebuilt image.
2. Move the [WSGI background refresher](../../src/qc_tool/frontend/wsgi.py) into
   a dedicated application service before enabling multiple frontend processes
   or replicas. Keep its existing maintenance admission contract.
3. Verify image digests/source identifiers in the deployment pipeline and
   rehearse interruption plus coordinated database/storage backup restoration
   in an isolated environment. The repository currently proves CI behavior,
   not an external production deployment/rollback/backup service.

## 9. Verification performed for this change

Final read-only browsing verification on 20 October 2026 used the existing frontend
review image with Linux Python **3.12.14** and Django **5.2.17**, the repository
mounted read-only, and disposable databases/storage. PostgreSQL used a dedicated
internal Docker network and a PostgreSQL 14 container with temporary data and
no published ports. Owned test containers/network were removed afterward.

| Check | Result |
| --- | --- |
| Full SQLite frontend/accounts/services/dashboard/database/uploaded-definition suite | 1,152 tests; OK with 9 skipped; 104.917 seconds |
| Full PostgreSQL frontend/accounts/services/dashboard/database/uploaded-definition suite | 1,152 tests; OK with 1 skipped; 113.330 seconds |
| Read-only browsing, SQL guard, maintenance UI and stream lifetime | Included in both complete backend suites, including normal-mode and active-maintenance generic-404 privacy regressions |
| Worker/auth/protocol suite in disposable Python 3.12 + Bottle container | 32 tests passed, including actual parent/child process-group termination |
| JavaScript event tests | 117 tests, passed |
| Maintainer tools | 14 tests passed |
| Models-only source tests and source gate | 5 tests passed; no migration packages or converter |
| Disposable PostgreSQL schema, repeated read-only application and role checks | Passed |
| Production-mode Django settings | `check --deploy` passed without issues |
| All three supported Compose profiles | `config --quiet` passed |
| Patch whitespace | `git diff --check` passed |
| Disposable browser preview | Admin enable → ready, authorized dashboard/Admin browsing and maintenance notice, disabled upload picker/Add, usable navigation inside disabled forms, then disable restoring controls; preview tab/container removed |

The PostgreSQL skip is the Python adapter for JavaScript tests because that
Python-only image does not contain Node.js; the host run separately passed all
117 JavaScript tests. SQLite's nine skips include backend-specific checks and
the same unavailable-Node adapter. PostgreSQL verification used no existing
database, published port or persistent volume. Its raw log and cleanup manifest
are retained locally at `/private/tmp/qc-tool-readonly-pg-44vqhgwy/verification.log`
and `result.json`; owned frontend/PostgreSQL containers and the internal network
were removed in the runner's final cleanup.

An earlier host-only intermittent upload lock failure was reproduced against
unchanged HEAD `e2e52a56` (4 of 30 runs). Upload-lock implementation was left
unchanged; both final Linux backend suites passed.

No existing application database was reset/upgraded, no product specification
was edited, and nothing was deployed. These results do not claim a remote CI
run, a rebuilt geospatial worker image, real QC-load interruption latency or a
production backup/restore rehearsal. Those remain release evidence requirements.
