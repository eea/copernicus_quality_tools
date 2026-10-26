---
title: Coordinated maintenance
parent: Architecture
nav_order: 8
---

# Coordinated maintenance

Maintenance closes admission to cooperating QC Tool writers and interrupts
queued/running QC work while authorized users retain read-only access. Readiness
requires drained application activity and positive worker acknowledgements. It
does not establish exclusive access against external SQL clients, storage
writers or deployment processes.

Use the [maintenance runbook](../deployment/maintenance.md) for administrator
and operator procedures, the [transfer architecture](record-transfer-design.md)
for backup/import recovery, and the [testing guide](../development/testing.md#read-only-maintenance-matrix)
for the read-only regression contract.

## Ownership

| Responsibility | Owner |
| --- | --- |
| Persistent state, generation and activity locks | [`services/maintenance/state.py`](../../src/qc_tool/frontend/dashboard/services/maintenance/state.py) |
| Enable, readiness, disable and verified worker retirement | [`services/maintenance/control.py`](../../src/qc_tool/frontend/dashboard/services/maintenance/control.py) |
| HTTP effect classification and read-only request/session handling | [`access/maintenance.py`](../../src/qc_tool/frontend/dashboard/access/maintenance.py), [`middleware.py`](../../src/qc_tool/frontend/dashboard/middleware.py) |
| Read-only SQL guard | [`services/maintenance/reads.py`](../../src/qc_tool/frontend/dashboard/services/maintenance/reads.py) |
| Operator authentication without SQL writes | [`accounts/authentication/maintenance.py`](../../src/qc_tool/frontend/accounts/authentication/maintenance.py), [`backends.py`](../../src/qc_tool/frontend/accounts/authentication/backends.py) |
| Worker message validation and authenticated transport | [`maintenance/protocol.py`](../../src/qc_tool/maintenance/protocol.py), [`services/maintenance/workers.py`](../../src/qc_tool/frontend/dashboard/services/maintenance/workers.py) |
| Claim/launch fencing and process-group interruption | [`worker/scheduler.py`](../../src/qc_tool/worker/scheduler.py) |
| Ready-operation barrier and durable transfer ownership | [`barrier.py`](../../src/qc_tool/frontend/dashboard/services/maintenance/barrier.py), [`operations.py`](../../src/qc_tool/frontend/dashboard/services/maintenance/operations.py) |

The Admin view and management command adapt the same maintenance service.
Accounts supplies identity and capability facts; dashboard policies retain
object ownership and product-scope checks. Worker lifecycle code stays outside
the raster/vector QC checks, whose identities and result semantics are unchanged.

## Admission and state transitions

The durable phases are `off`, `stopping` and `ready`. An unreadable state is an
unavailable condition that refuses ordinary application access; it is never
interpreted as OFF.

1. **Enable:** under the control lock, persist `enabled=true`, a new generation
   and `phase=stopping` before waiting for activity to finish. New ordinary
   mutations are refused immediately.
2. **Establish readiness:** acquire the exclusive activity barrier, confirm each
   known worker has stopped, then reconcile waiting/running jobs through the
   existing terminal-status services. Only successful completion records `ready`
   and `readiness_checked_at`. Missing worker addresses, database failures and
   incomplete acknowledgements retain the barrier and explain the blocker.
3. **Disable:** require the expected generation, readiness and no owning transfer.
   Persist OFF with a new generation. Interrupted jobs remain historical error
   outcomes; users must submit them again.

Requests admitted before enable hold a shared activity lock through completion,
including streamed response cleanup. Background writers and queue claims use
the same admission contract. Reads started after the fence do not hold the
writer-drain lock or postpone readiness. Rechecking readiness invalidates the
previous observation while it gathers fresh evidence; automatic progress does
not invalidate readiness already established for the same generation.

HTTP effects are classified by named route using `request.path_info`, so the
policy also applies beneath a deployment URL prefix. Ordinary uploads,
registrations, QC claims, review/publication and Admin mutations are blocked.
Resumable-upload GET probes are write-classified because they can create locks.
Explicit POST reads retain CSRF and normal authorization. Maintenance controls
are narrowly classified routes whose handlers still authorize and validate the
specific action; there is no blanket Admin write exemption.

## Worker acknowledgement

Workers register their canonical address before claiming work, start paused and
poll the frontend admission authority even when their job slots are occupied.
Loss of authority pauses claims/launches and requests interruption of owned work.
Generation checks reject stale or conflicting commands that could reopen a
worker after a newer pause.

The frontend uses bounded parallel probes over the authenticated worker channel.
The shared protocol requires the expected enabled state, generation and an
explicit `quiescent` acknowledgement. Quiescence means no outstanding claims or
registered job controllers. Unreachable, incompatible or still-stopping workers
prevent readiness; a timeout is not evidence that their work exited.

Controllers own process groups, request TERM, escalate to KILL when necessary
and wait for the owned work to disappear. A SQL job-status change alone is not
proof of process termination. Because controller ownership is held in memory,
replace a failed worker as a whole container rather than restarting only its
scheduler while descendant processes may survive. A fatal scheduler failure
closes admission and makes its health response unhealthy. Independent work
already submitted to an external service still needs that service's cleanup.

## Browsing and sign-in

Existing valid browser sessions and API credentials keep their normal
permission, ownership and product-scope checks. The request/stream SQL guard
rejects incidental database writes; read-only session handling, token-use
suppression and disabled status refresh avoid expected write side effects.
This guards QC Tool's own query paths, not arbitrary SQL from external clients.

Active QC Tool administrators and product managers can sign in through the
application or Admin login during maintenance. Generic staff status alone does
not qualify. Sign-in uses a signed-cookie session lasting at most 30 minutes,
bound to the maintenance generation and authentication database. It creates no
SQL session, `last_login` update or password-hash upgrade. Product managers gain
no maintenance-control or transfer authority. Ordinary new sign-ins, logout and
account mutations remain blocked. Ending maintenance or changing its generation
expires maintenance authentication; normal sign-in is required afterward.

After an explicit database switch, an administrator's maintenance credential can
remain bound to its source database. The immediately previous source is the
only retained sign-in fallback, confined to that maintenance generation; it
does not grant arbitrary access to older database copies. If the selected copy
is unavailable, [startup recovery](../../src/qc_tool/database/recovery.py) can
admit the recovery UI only after checking the ready generation, recorded source
verification, retained database identity/current schema and administrator
access. It does not initialize, repair or select either database. The normal
database readiness check remains strict.

## Persistent authority and recovery boundaries

State and locks live in private persistent `WORK_DIR/maintenance`, independent
of the application database. Atomic replacement and file/directory
synchronization publish complete state; bounded versioned JSON validation and
regular no-follow lock files reject unsafe authority. All participating
processes and operator commands must use the same directory and a filesystem
with working POSIX locks. The supported topology remains one frontend
process/container with multiple workers.

Only the process that exclusively creates a new maintenance directory may
initialize OFF. An existing directory with missing/corrupt state fails closed;
do not precreate an empty maintenance directory or remove state/locks to reopen
traffic. Replacing the entire directory or volume loses its history and cannot
be distinguished locally from a new installation. Preserve storage identity
and follow the [persistent storage requirements](../deployment/eea-storage.md).

Synchronous administrative storage actions use the ready barrier while retaining
their own authorization and review checks. Background transfers additionally
hold a durable operation pin. Process death and elapsed time do not release it;
the transfer's execution lock, journal and SQL receipt determine safe recovery.
Never remove a pin or edit authority files to bypass an incomplete operation.
An environment-forced `MAINTENANCE_MODE` also cannot be turned off by the UI.

Ready maintenance fences cooperating writers while readers may still have open
database connections. Stop services and close readers before DDL or replacing
a database; coordinate external writers separately. Back up the database with
its referenced files, credentials and original specifications, and verify a
restore. The [models-only database policy](../../src/qc_tool/database/README.md)
is unchanged: initialization requires an entirely empty target, existing matching
schemas are read-only no-ops, and incompatible occupied schemas are refused.
Maintenance does not authorize schema repair, reset, migration or adoption.
