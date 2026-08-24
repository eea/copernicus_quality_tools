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

| Area | Typical permission |
| --- | --- |
| Deliveries, history, result downloads | `view_deliveries` plus object scope |
| Upload page | `upload_delivery` |
| Job setup | `run_qc` |
| Boundaries and announcement | `manage_configuration` |

## Session data and mutations

These return structured JSON 401/403 responses. Mutations use POST and remain
CSRF-protected.

| Action | Permission |
| --- | --- |
| List/report data | `view_deliveries` plus object scope |
| Upload chunks | `upload_delivery` |
| Create job | `run_qc` plus owner/admin |
| Delete delivery/job | `delete_delivery` plus owner/admin |
| Submit delivery | `submit_delivery` plus owner/admin |
| Boundary upload/data | `manage_configuration` |

## API operations

Operational `/api/*` routes require a Bearer credential. They use the same
Django permissions and object policy as the browser.

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
