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

The Django login page and the Admin login entrypoint must also be reachable
without an existing session. Successful Admin access and every application page
remain private.

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

## Superseded browser paths

Old bookmarks are supported temporarily by authenticated, one-hop redirects.
Redirects preserve the query string, and application links must always reverse
the canonical route name so a redirect chain cannot develop.

| Superseded path | Canonical destination |
| --- | --- |
| `/upload/` | `/deliveries/upload/` |
| `/setup_job` | `/deliveries/jobs/new/` |
| `/job_history/<delivery_id>/` | `/deliveries/jobs/<delivery_id>/` |
| `/deliveries/job_history/<delivery_id>/` | `/deliveries/jobs/<delivery_id>/` |
| `/result/<job_uuid>` | `/deliveries/job-result/<job_uuid>/` |
| `/deliveries/result/<job_uuid>` | `/deliveries/job-result/<job_uuid>/` |
| `/boundaries_upload/` | `/boundaries/upload/` |
| `/submissions/` | `/products/submissions` |

These aliases live only in `frontend/dashboard/urls/compatibility.py`. Remove
an alias after its deprecation window instead of adding a redirect from one
legacy path to another.

## Session data and mutations

These return structured JSON 401/403 responses. Mutations use POST and remain
CSRF-protected.

The browser hierarchy change does not rename internal transport, data,
artifact, or mutation contracts. Existing `/resumable_upload/`, `/data/*`,
`/create_job`, `/job/*`, `/delivery/*`, and `/attachment/*` consumers continue
to use their established paths. `/products/list/` is the canonical
authenticated product-list JSON endpoint; the existing product data endpoint
remains a direct JSON compatibility alias while consumers transition.

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

## Worker

`POST /pull_job` is private machine-to-machine traffic authenticated by the
`WorkerToken` header. It does not use a user permission because possession of
the shared worker credential is the service authorization boundary.

When adding or renaming a named dashboard route, update the registry and exact
route-policy tests in the same change. A route must never rely on a hidden UI
control for authorization.
