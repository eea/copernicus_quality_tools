---
title: Maintenance mode
parent: Deployment
nav_order: 3
---

# Maintenance mode

Administrative [record transfers](../user-guide/record-transfers.md) require
maintenance readiness and hold a durable operation pin while running. The
maintenance panel links to the owning transfer; maintenance changes are blocked
until it finishes or is safely recovered/cancelled. Process death and elapsed
time never release this pin. `maintenance status` includes `transfer_operation`.
Use `data_transfer status UUID` and the same Admin recovery controls described
in the transfer guide. Never delete a pin to bypass uncertain SQL/file state.

Maintenance stops cooperating QC Tool writers while signed-in users and API
clients continue browsing authorized data in read-only mode. This lets an
operator back up the application database and its files together. Maintenance
does not run backups, migrations
or SQL DDL, and it does not set PostgreSQL to read-only. The
[architecture review](../architecture/maintenance-research.md) maps deployment,
CI/CD, execution and storage ownership from the checked-in source.

## Requirements and deployment

Control maintenance through **Admin → Maintenance mode** or the operator
`maintenance` command. Both use the same persistent application state. Docker
manifests need no maintenance setting, and switching modes does not require a
container restart.

Deploy the matching frontend and worker source/images together. An old worker
does not implement the maintenance acknowledgment; it prevents readiness.
Maintenance itself adds no application-model change. Administrative record
transfers require the current `qc_database_transfer_receipt` model table; an
earlier draft database must be preserved and moved through a separately reviewed
cutover, never repaired at startup. The database policy stays `draft` with no baselines, first-party migration definitions or
initial snapshots. Keep using `database plan|check|apply` from the
[database runbook](../../src/qc_tool/database/MIGRATIONS.md).

All frontend processes/containers and maintenance commands must share the same
persistent `WORK_DIR/maintenance` directory, with working cross-process POSIX
`flock`, atomic rename and filesystem synchronization. Keep its ownership with
the frontend runtime user. A test may override `QC_TOOL_MAINTENANCE_DIR` through
Django settings; ordinary deployments use `WORK_DIR`. Do not delete the state or
lock files, replace their volume, or restore an older state while services run.
Such a change loses admission/generation history. Verify the storage's locking
behavior before deploying on NFS or another distributed filesystem.

At first use, the application creates the maintenance directory privately and
writes initial OFF state. Only the process that creates a new directory may
initialize it. An existing directory with missing state fails closed, including
an otherwise empty directory: the application cannot interpret lost state as
permission to reopen traffic. Do not precreate an empty maintenance directory;
let the application initialize it beneath the provisioned `WORK_DIR`.

State uses a strictly validated, bounded, versioned JSON format. Lock files must
be regular files, are opened without following symlinks and cannot be writable
by a group or the public. Unsafe paths, corrupt/incompatible state or incomplete
bootstrap block admission and need deliberate offline operator recovery.
Deleting the entire maintenance directory or substituting a new empty volume
is outside this protection: local files cannot distinguish that action from a
first installation. Preserve the state/volume identity across restarts and
restore operations; never use its removal as an OFF switch.

The supported topology remains one frontend process/container; startup rejects
`QC_TOOL_WEB_WORKERS` values other than `1`. Workers can run
separately on their existing shared input/work/boundary storage. Every worker
registers its canonical network address before it can claim a job. Its
authenticated admission poll runs even when all job slots are occupied; it
starts paused and fails closed if the frontend state cannot be obtained. Claim
batches have both a slot-count limit and a polling deadline, so a steady stream
of short jobs cannot postpone the next authority check indefinitely. A fatal
scheduler-loop error closes admission, requests interruption of owned work and
makes the worker health response unhealthy instead of leaving a live HTTP
server beside a dead scheduler.

Worker process ownership is held in the scheduler's memory. Restart the whole
worker container when replacing or recovering that scheduler; do not restart
only `qc_tool.worker.scheduler` or use `supervisorctl restart scheduler` while
its old job processes can survive. The supplied Supervisor configuration sets
`autorestart=false` for the scheduler and shuts down the container when it
exits. Container replacement stops its remaining process namespace before a
fresh scheduler starts. An alternative supervisor must provide the same
whole-unit stop and reap behavior. A standalone scheduler restart in a surviving
process namespace is unsupported: its empty controller table cannot establish
that older validator process groups stopped. If this occurs, stop and verify
the complete worker unit, then repeat readiness checks or use verified worker
retirement below.

The proxy must allow worker POSTs to `/worker_maintenance` and frontend PUTs to
each worker's authenticated `/maintenance`. Preserve direct worker socket
addresses for the existing canonical IP/port trust contract. Do not route these
callbacks through a proxy which makes every worker appear to have one address.
Keep worker endpoints private. `/health` remains a public, non-sensitive
liveness check during maintenance; it does not certify database readiness.
The worker health endpoint returns 503 if its scheduler has failed.
Use `/health` for frontend liveness instead of a login or data page. Login pages
remain visible with a maintenance notice. Active QC Tool administrators and
product managers can sign in during maintenance without writing to the database;
ordinary users cannot start a new session until maintenance ends.

The paths above are application-relative examples. When the frontend is mounted
under a URL prefix, the named control routes and middleware use Django's
application path information, so the same control/admission policy applies under
that prefix. Configure the external proxy and worker polling URL consistently.

## Administrator procedure

1. Sign in as a QC Tool administrator and open **Admin → Maintenance mode**.
   Superusers and the existing administrator role can operate it. Product
   managers and ordinary staff cannot operate these controls. An administrator
   whose session expires can sign in again while maintenance stays enabled.
2. Select **Turn on maintenance**. This persists the
   writer fence immediately. Browser/API uploads, resumable chunks and probes,
   registrations, QC claims, publication/review actions, account changes and
   ordinary Admin mutations return 503 before writing. Existing admitted
   requests finish, including complete streamed responses. Authorized browsing,
   downloads and exports remain available with a maintenance notification;
   controls that change data are disabled.
3. While the page reports **Turning on maintenance**, checks run automatically.
   With JavaScript disabled, use **Update progress**. The worker
   pauses claims and launches, terminates the complete owned process group with
   TERM then KILL if needed, and waits for processes/controllers and outstanding
   claims to disappear. A missing, incompatible or unreachable worker is a
   blocker, never proof that it stopped. The frontend background refresher
   follows the same admission barrier as web requests. Worker probes run in a
   bounded pool of at most eight concurrent requests with a ten-second probing
   budget per check. Any unconfirmed worker keeps the state stopping. Persistent
   blockers appear in **Technical details**; checks continue while this page is
   open. Connection failures offer a retry without turning maintenance off.
4. **Maintenance is on** (the internal `ready` phase) means the pre-existing writer barrier drained, every registered
   worker positively acknowledged the current generation and quiescence, and
   queued/running jobs were finalized through existing locked lifecycle services
   using the established `error` state. Previously terminal jobs and delivery
   history are retained. No interrupted job is silently retried. New read-only
   requests do not hold the writer barrier and can continue while ready.
5. Perform the backup/maintenance procedure below. Keep the mode on throughout.
6. Check the intended schema/image and restore evidence, then select **Turn off
   maintenance**. Workers receive the new generation through their regular
   authenticated poll. Users may upload and explicitly rerun interrupted jobs.

Progress checks use serialized, CSRF-protected administrator POST requests while
work is stopping. They stop once ready or when a transfer takes ownership. A late
automatic request cannot invalidate readiness that another request completed.
After first-use storage initialization, GET reads status without starting
maintenance or mutating application database records; the UI never starts
maintenance through a link.
Generation checks reject stale tabs/commands. A previous readiness observation
does not establish current worker reachability. An operator can explicitly run
`maintenance check --generation N` before external database work if time has
elapsed or a service restarted. An explicit recheck first records `stopping`
and establishes evidence again. **Technical details** shows the last
confirmed readiness timestamp (`readiness_checked_at`), separate from the time
maintenance was enabled. That timestamp records an observation, not a guarantee
that a later backup or external SQL session is isolated. Administrator actions
are recorded in persistent state and application logs without job credentials.

## Read-only browsing

Existing authenticated browser sessions and valid API credentials retain their
usual account, product-scope and ownership restrictions. Users can view pages,
inspect Admin records, filter tables, read history/results and download retained
files. GET/HEAD reads remain subject to each route's supported methods. The
audited POST routes `table_export`, `delivery_upload_check` and `update_job` are
also available as reads: exports convert a bounded table snapshot, duplicate
checks inspect existing data, and job polling returns persisted status without
refreshing it from workers. Session POST reads retain their CSRF protection.

Maintenance browsing uses read-only sessions, including invalid-session handling,
asynchronous session methods and `SESSION_SAVE_EVERY_REQUEST`. API authentication
does not update token-use timestamps. History/status routes suppress persistence
refresh, and a database-write guard rejects unexpected ORM writes from a read
request, including lazy Admin content-type creation. The normal background
refresher remains paused. A missing/corrupt maintenance state still fails closed
with 503 rather than permitting an unclassified request.

The interface shows a persistent maintenance notice and disables mutating
controls. Server-side route admission remains authoritative if a client removes
the disabled attribute or calls a URL directly. Resumable-upload GET probes are
blocked as well as POST uploads because their lock-directory/file operations
change shared storage. Ordinary Admin POSTs, profile/password/API-token changes,
and logout remain blocked.

### Signing in during maintenance

Both `/accounts/login/` and `/admin/login/` use the existing application login
interface. Active accounts recognized by QC Tool as administrators or product
managers can sign in; generic staff status alone does not qualify. Ordinary
users with an existing valid session can keep browsing, but cannot sign in anew
while maintenance is enabled.

A maintenance sign-in uses a Django signed-cookie session with a maximum
30-minute lifetime in the normal session cookie. Authentication is bound to the
current maintenance generation while the mode is on; it expires when that
generation changes or maintenance ends, even before the time limit. It creates
no SQL session record and
does not update `last_login` or upgrade the stored password hash. Normal account,
product-scope and permission checks still apply. Product-manager sign-in grants
no maintenance-control or record-transfer authority; those controls remain
administrator-only. Uploads, QC work and all other ordinary database mutations
remain fenced for every role.

An explicit Admin database switch keeps the operator's signed credential bound
to its original authentication database. Its active account, roles and password
hash remain checked on every request; a product manager cannot carry this
credential into another database. During the same maintenance generation only,
an administrator can sign in against the immediately previous source if the
selected copy is unavailable. Older retained primary databases are not additional
sign-in fallbacks. Reopening requires verified administrator access in the active
copy and ends maintenance authentication. All frontend instances must share the
private transfer directory and configured primary connection so they follow the
same deployment-bound selection pointer. Preserve it with the operation journals.

If the selected copy becomes unavailable, restarting the frontend can still
admit the maintenance recovery UI. Startup checks the retained source identity,
current schema and a usable administrator, requires recorded source verification
and the same ready maintenance generation, and leaves both databases and the
selection untouched. Local initialization, demo bootstrap and development-server
database checks are skipped in recovery. An old SQL-session cookie is treated as
anonymous if its database cannot be read; an administrator can then use the
retained-source sign-in fallback and the reviewed **Switch back** action. Normal
`database check` remains strict; this startup-only allowance is requested with
`database check --allow-maintenance-recovery`.

If this short session expires, an eligible user can sign in again. An
administrator can therefore return to **Admin → Maintenance mode** and disable
maintenance through the usual controls after the operator's work is complete.
That action ends maintenance authentication. On the next request, an account
using this short session must sign in normally through the configured session
backend before resuming ordinary operations. Existing normal sessions keep
their usual behavior. New sign-ins after maintenance use the configured session
backend again.
Logout remains unavailable while maintenance is enabled.

The dedicated administrator maintenance actions and authenticated worker state
channel remain operational. Those controlled state transitions are separate
from ordinary user mutations and still require their existing authorization.

## Backup and schema operations

Use the deployment's existing Compose command setup from [Operations](operations.md).
After confirming **ready**, record source commit/image digests, maintenance
generation, timestamp and effective volume/database inventory. Isolate any
external writers, scheduled operator commands or older application instances
that do not participate in this protocol.

Back up the frontend database and `INCOMING_DIR`, `WORK_DIR` (including maintenance
state), `BOUNDARY_DIR` with its generation pointer, `SUBMISSION_DIR`, and any
external `S3_CREDENTIALS_DIR`. Retain original specification/catalog snapshots,
configuration and secret references securely. Preserve restricted credential
file permissions and encrypt sensitive backups. Database references and retained
publication receipts must reconcile with the matching files.

For the PostgreSQL profile, an example logical archive is:

```bash
qc_compose exec -T userdb \
  pg_dump --username qc_user --dbname qc_tool --format custom \
  > qc-tool-userdb.dump
```

Adapt service/database/user names to the effective deployment and check command
exit status and stderr. PostgreSQL `pg_dump` already takes a consistent SQL
snapshot without blocking ordinary writers; the maintenance fence additionally
coordinates application files. It covers one database, while cluster globals
such as roles require separate backup. See the official
[PostgreSQL 14 pg_dump contract](https://www.postgresql.org/docs/14/app-pgdump.html).
Use the supported SQLite backup API or a fully quiescent database snapshot for
SQLite; do not copy a live DB file without its consistency requirements.

Record checksums and rehearse restoration into a separate fresh disposable
target. Verify schema with `database check`, record/access integrity, retained
artifact manifests/checksums, storage and actual application access. An archive
which has not been restored is unverified recovery evidence.

For manual DDL or replacing/restoring the serving database, stop every frontend/worker service
and external DB writer/reader that may hold connections. Read-only browsing can
retain SQL connections and streamed downloads, so close readers as part of that
service shutdown. UI readiness is
application quiescence, not an exclusive PostgreSQL lock or a credential
revocation. The persisted maintenance flag remains on when the frontend starts
again. Restart matching services, validate the target and then resume via UI or
the command below. v3.0.0 never upgrades/repairs a nonempty schema; changed models
need a separate prepared target. A migration-managed transition belongs to a
separate reviewed v3.0.1-or-later release.

The Admin native restore instead prepares a separate empty database while the
serving copy remains intact. Its separately reviewed **Switch active database**
action keeps maintenance on and retains the previous copy. **Switch back** is
limited to the same uninterrupted maintenance generation before reopening;
after ordinary work resumes, use a new reviewed transfer instead. See
[Import and export records](../user-guide/record-transfers.md).

Process termination may retain incomplete job files or worker-local temporary
PostGIS schemas. Keep them for diagnosis; no automatic cleanup/reset is done.
INSPIRE may run in a separately supervised/remote validator: stopping the local
job cancels its client but cannot certify that remote computation stopped.
That validator does not write the frontend application DB. Stop its service too
when the operator's procedure requires all computation to stop.

## Operator recovery

The command line remains a fallback when the UI, account database or maintenance
state cannot be accessed. An expired administrator session alone does not
require it: sign in again through the normal login page while maintenance is on.

Use the exact deployed source, settings, shared storage and runtime identity.
These commands do not initialize, reset or upgrade a database:

```bash
python3 -m qc_tool.frontend.manage maintenance status
python3 -m qc_tool.frontend.manage maintenance on
python3 -m qc_tool.frontend.manage maintenance check --generation 1
python3 -m qc_tool.frontend.manage maintenance off --generation 1
```

`on` enables and attempts readiness once; `check` retries stopping and `off`
requires ready. `on` and `check` print the resulting state and return a nonzero
exit status while stopping remains incomplete. A successful command can
therefore guard a following backup step; do not discard its exit status or run
the backup unconditionally after it. `status` reports state without attempting
readiness; first use can initialize the private state directory as described
above. Use the actual generation printed by `status`, rather than the
example `1`. With no explicit generation, ordinary commands snapshot the current
one before executing. Nothing bypasses outstanding worker acknowledgments.
The state remains enabled when stopping fails. If the app DB is unavailable,
`status` still reads storage; `check` needs the DB and must be retried after
restoration. An unreadable/corrupt state or broken locking closes application
admission. Preserve evidence and repair storage as an operator; never delete
state to reopen traffic.

Registered workers are retained until explicitly retired, including old
container addresses. First verify the worker host/container and **all** its job
processes are stopped (not merely unreachable), then retire only that origin:

```bash
python3 -m qc_tool.frontend.manage maintenance retire-worker \
  --worker-url http://192.0.2.10:8000/ \
  --generation 1 --verified-stopped
python3 -m qc_tool.frontend.manage maintenance check --generation 2
```

Retirement requires maintenance on and drained application activity. It finalizes
running jobs assigned to the verified-stopped worker through the same lifecycle
service, removes its registry entry and advances the generation. Check readiness
again. This is an explicit operator attestation, not automatic recovery from a
timeout. Do not attest a worker you cannot verify stopped.

Older custom deployments may still supply `MAINTENANCE_MODE=yes`. The runtime
retains this compatibility override, but current Docker manifests do not set it
and it is not needed for maintenance control. If an older deployment supplies
it, the override forces a fresh durable maintenance generation and prevents
UI/command disable. Remove it from that deployment's environment and restart
the frontend after coordinating the operation; the persistent application flag
stays enabled until the normal ready/off procedure finishes.

## Verification and evidence limits

Frontend tests cover role/CSRF controls, stale generations, blocked browser/API
paths, worker authentication, request and streamed-response draining, background
refresh suppression, invalid-session writes, unreachable workers and terminal
job preservation. Scoped regressions also cover prefixed control routes, bounded
parallel probing, readiness timestamps, command exit status and service-owned
worker retirement. Worker tests exercise claim/launch races, bounded admission
polling under sustained work, fatal-loop health, fail-closed polling and real
parent/descendant process-group termination. CI runs these focused
worker tests and discovers frontend tests in its SQLite/PostgreSQL matrix.
The [read-only maintenance matrix](../development/testing.md#read-only-maintenance-matrix)
also requires zero-write browsing, persisted-status polling, safe POST read CSRF,
disabled controls and continued readiness while readers remain active.

These checks do not certify a production filesystem's distributed lock behavior,
a deployed image pair, network topology, backup restoration or external-writer
isolation. Rehearse the complete on → ready → backup/restore → off procedure in
the target deployment before relying on it operationally.
