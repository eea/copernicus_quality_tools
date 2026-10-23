---
title: Routes and permissions
parent: Reference
nav_order: 3
---

# Routes and permissions

This is a conceptual reference. The executable source of truth is
`frontend/dashboard/access/routes/private.py` and `public.py`, covered by the
route-policy test matrix.

## Public dashboard routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/` | Human-readable API documentation |
| GET | `/api/openapi.json` | OpenAPI schema |

The application login interface is reachable without an existing session at
`/accounts/login/` and `/admin/login/`. Successful Admin access and every
application page remain private. During maintenance, active QC Tool
administrators and product managers can sign in through these entrypoints;
generic staff status alone does not qualify. Existing ordinary-user sessions
retain their usual authorized read access, while new ordinary-user sign-ins
wait until maintenance ends.

## Browser pages

Anonymous users are redirected to login. Authenticated users without the
permission receive an HTML 403 response.

The table below lists canonical browser paths. Job history belongs to a
delivery, so its identifier is the integer delivery primary key. A result
belongs to one QC job, so its identifier is the job UUID.

| Area | Canonical path | Response |
| --- | --- | --- |
| Dashboard | `/` | Workspace home page |
| Deliveries | `/deliveries/` | Delivery workspace |
| Delivery upload | `/deliveries/upload/` | Upload page |
| New QC job | `/deliveries/jobs/new/` | Job setup page |
| Delivery job history | `/deliveries/jobs/<delivery_id>/` | Jobs for one delivery |
| QC job result | `/deliveries/job-result/<job_uuid>/` | Result for one job |
| Original QC input | `/data/job/<job_uuid>/input.zip` | Job-scoped download; verifies the ZIP against that run's recorded checksum |
| Products | `/products/` | Product catalog page |
| Product submission review | `/products/submissions` | Assigned-manager and administrator review queue |
| Product detail | `/products/<product_ident>/` | HTML detail page for one product |
| Product list | `/products/list/` | Authenticated session JSON; this is not an HTML page |
| Boundaries | `/boundaries/` | Boundary catalog page |
| Boundary upload | `/boundaries/upload/` | Boundary package management page |
| API access | `/api/` | Human-readable API documentation |

| Area | Typical permission |
| --- | --- |
| Dashboard and product catalog | `view_deliveries` |
| Product submission review | Administrator or assigned product manager |
| Deliveries, history, result downloads | `view_deliveries` plus object scope |
| Upload page | `upload_delivery` |
| Job setup | `run_qc` |
| Boundary and announcement pages (read-only) | `view_deliveries` |
| Replace the boundary package or update the announcement | `manage_configuration` |

Product metadata follows the catalog-page permission. Product-wide delivery
coverage remains scoped to administrators and product managers assigned to the
requested product; hiding a control in the template is not an authorization
boundary.

Product identifiers are canonical lowercase ASCII values that start with a
letter or number and then use letters, numbers, `_`, `-`, or `.`. The literal
`list`, `upload` and `submissions` are reserved by Products workspace routes and are rejected at
catalog, job/API, and worker trust boundaries. A product detail page shows each
current release stream separately; it never chooses an arbitrary release or
merges denominators.

## Browser route policy

Application links reverse the canonical route names shown above. Superseded
page paths and the old product-list JSON alias are not registered in this
major release. `/products/submissions/` redirects to `/products/submissions`
while preserving its query string.

## Session data and mutations

These return structured JSON 401/403 responses. Mutations use POST and remain
CSRF-protected.

The browser hierarchy change does not rename internal transport, data,
artifact, or mutation contracts. Existing `/resumable_upload/`, `/data/*`,
`/create_job`, `/job/*`, `/delivery/*`, and `/attachment/*` consumers continue
to use their established paths. `/products/list/` is the canonical
authenticated product-list JSON endpoint.

| Action | Permission |
| --- | --- |
| List/report data | `view_deliveries` plus object scope |
| Upload chunks | `upload_delivery` |
| Create job | `run_qc` plus owner/admin |
| Delete unsubmitted delivery | `delete_delivery` plus owner/admin |
| Submit delivery | `submit_delivery` plus owner/admin |
| List boundary files | `view_deliveries` |
| Upload and activate a replacement boundary package | `manage_configuration` |

No role can delete a QC job independently, including administrators. An explicit,
permitted delivery deletion removes its associated job records. Submitted
deliveries and their publication history are protected; replacing or correcting a
delivery preserves the previous revision and its jobs.

## API operations

Operational `/api/*` routes require a Bearer credential. They use the same
Django permissions and object policy as the browser.

The operational `/api/*` paths and payloads are unchanged by the browser URL
reorganization. They must not be routed through browser compatibility
redirects.

| Operation | Permission |
| --- | --- |
| Register uploaded/S3 delivery | `upload_delivery` |
| List deliveries/products/results/history | `view_deliveries` plus scope |
| Create job | `run_qc` plus owner/admin |
| Submit delivery | `submit_delivery` plus owner/admin |

## Administrator record transfers

The Admin header has **Overview**, **User management**, **Database** and
**Storage**. `GET /admin/users/` (`admin_user_management`) lists only account
actions available through registered ModelAdmin permissions. User-profile
transfers require the QC administrator role even when ordinary account editors
are available to staff. Loaded transfer profiles determine the active section.

These focused Admin routes are declared in `frontend/urls.py`, outside the
dashboard route registry. They require an active administrator session and the
same QC Tool administrator check as maintenance controls. Product-manager,
generic staff, model-view permissions and personal access tokens do not grant
transfer authority. POST actions remain CSRF protected.

| Method | Path | Route name | Purpose |
| --- | --- | --- | --- |
| GET, POST | `/admin/database/` | `admin_data_transfer` | Default GET: records import/export, full backups, explicit read-only schema check, maintenance and collapsed table browser. `?tab=transfers`: compatibility transfer chooser. Reviewed transfer POSTs retain their service controls. |
| GET | `/admin/database/records/<table>/` | `admin_database_records` | Administrator-only paginated inspection of explicitly allowed model tables; sensitive fields excluded |
| GET | `/admin/database/records/<table>/<pk>/` | `admin_database_record` | Allowed record fields, FK/dependency navigation and links to guarded editors; no session-key detail route |
| GET | `/admin/database/<operation_id>/status/` | `admin_data_transfer_status` | Read an authorized operation's public status |
| GET | `/admin/database/<operation_id>/download/` | `admin_data_transfer_download` | Download a completed verified export package |

The slashless `/admin/database` and previous `/admin/data-transfer/` paths
(including their status/download endpoints) are direct compatibility aliases.
They preserve submitted POST bodies and use the same administrator and maintenance
policies. New navigation and operation links use `/admin/database/`.

Only the named transfer controls and their compatibility aliases are mutation controls
during maintenance. Record-list/detail routes are ordinary read routes: POSTs are
refused, and they never inherit the transfer exemption. Mutations use the existing
model Admin URLs with CSRF, per-model policy and the ordinary maintenance write fence.
The transfer service
requires maintenance readiness for export previews, import planning and execution;
it pins the maintenance generation for a running transfer. Staging writes only
private control storage. Ordinary Admin mutation forms remain blocked. Every
operation status and download repeats administrator authorization. The service
revalidates plan hashes, source/target state and supported schemas before writes.
See the [record transfer guide](../user-guide/record-transfers.md).

## Administrator server storage

All Storage routes require the QC administrator role and an active Admin
session. Generic staff, product managers and API credentials cannot use them.

| Method | Path | Route name | Purpose |
| --- | --- | --- | --- |
| GET | `/admin/storage/` | `admin_storage` | Configured storage areas, folder search and paginated listings; independent of delivery rows |
| GET | `/admin/storage/file/` | `admin_storage_file` | Confined file metadata, exact database links and optional full-file checksum verification |
| GET | `/admin/storage/download/` | `admin_storage_download` | Safe descriptor-backed attachment; private, non-cacheable, sandboxed response |
| GET | `/admin/storage/trash/` | `admin_storage_trash` | Read private trash journals and available restoration actions |
| POST | `/admin/storage/action/` | `admin_storage_action` | Explicit reviewed move-to-trash or no-overwrite restore |

Only `admin_storage_action` is a maintenance mutation control. Browse, details,
download and trash-list routes are ordinary read routes; POSTs are refused and
receive no write-fence exemption. Actions retain CSRF protection, revalidate an
administrator on the selected database, require the reviewed maintenance
generation, acquire the transfer execution lease and shared exclusive activity
barrier, and recheck file identity and database references before changing files.
They never write application SQL rows. Linked/immutable files cannot enter trash;
a matching retained incoming ZIP can be restored after record import only with
recorded checksum/size evidence. No permanent-delete action is exposed.

## Worker

`POST /worker_maintenance` reports the maintenance generation to authenticated
workers and remains available during a pause. `PUT /maintenance` on a worker
accepts authenticated pause commands; neither endpoint accepts browser sessions
as a substitute for the shared worker credential. `/admin/maintenance/` is a
CSRF-protected administrator-only control, available to an existing session
during maintenance or after an administrator signs in again. `/health` is a
non-sensitive liveness probe handled before
session/database access. During maintenance, authorized application/Admin
GET/HEAD reads retain their normal route/access contracts with read-only
sessions. The audited POST routes `table_export`, `update_job` (persisted-status
read) and `delivery_upload_check` also remain available; their normal permission
and CSRF checks still apply. Ordinary mutations return 503, including logout
and ordinary Admin POSTs. Eligible maintenance sign-ins use a Django signed-cookie
session in the normal session cookie for at most 30 minutes, bound to the current
maintenance generation while the mode is on, without SQL session,
`last_login` or password-hash writes. This exception does not grant product
managers administrator-only maintenance or transfer access, or permit any
ordinary database mutation. Maintenance authentication expires when the mode
ends or its generation changes. An administrator can disable maintenance, then
the next request requires normal sign-in through the configured session backend
before ordinary operations resume for that maintenance session. After an explicit
database switch, the signed operator credential remains bound to its original
database; live account/password/role checks use a pinned read-only connection.
Only administrators may retain that origin access across a switch. Source-admin
sign-in fallback is limited to the same uninterrupted maintenance generation.
Explicit switch/rollback actions remain administrator-only and require reviewed
destination and storage/access confirmation. Existing normal sessions keep their
usual behavior. Resumable-upload GET probes remain blocked because
they create filesystem locks. See [Maintenance mode](../deployment/maintenance.md).

`POST /pull_job` is private machine-to-machine traffic authenticated by the
`WorkerToken` header. It does not use a user permission because possession of
the shared worker credential is the service authorization boundary.

When adding or renaming a named dashboard route, update the registry and exact
route-policy tests in the same change. A route must never rely on a hidden UI
control for authorization.
