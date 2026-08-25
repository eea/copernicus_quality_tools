---
title: Authentication and authorization
parent: Architecture
nav_order: 3
---

# Authentication and authorization

QC Tool separates four questions:

1. Is the route public or private?
2. How is the caller authenticated?
3. Which capability does the caller need?
4. May the caller access this specific delivery or job?

## Authentication modes

| Caller | Credential | Intended endpoints |
| --- | --- | --- |
| Browser user | Django session cookie + CSRF token | HTML pages and dashboard data |
| API client | `Authorization: Bearer <one-time-issued credential>` | `/api/*` operations |
| Worker | `Authorization: WorkerToken <shared token>` | internal `POST /pull_job` |
| Anonymous visitor | none | Login/authentication entry pages, API documentation, and OpenAPI schema |

API and worker credentials are never accepted in query strings. Their endpoints
are CSRF-exempt because they do not authenticate with cookies; browser
mutations remain CSRF-protected.

## Route policy

Every named dashboard route is registered through
`dashboard/urls/_helpers.py` and must exist in the route-policy registry.

A route policy declares:

- `PUBLIC` or `PRIVATE` visibility;
- session, API credential, or worker-token authentication;
- allowed HTTP methods;
- required Django permission for user/API routes;
- browser redirect, JSON, or status-only denial behavior.

Unknown combinations fail during import. Django's global
`LoginRequiredMiddleware` is the safety net for future views outside the
registry.

## Roles and permissions

Roles are Django groups that bundle permissions. They are not hard-coded checks
inside views.

| Role | Purpose | Permission bundle |
| --- | --- | --- |
| `default` | Baseline for every active user | view, upload, run QC, delete own, submit own, change password |
| `product_manager` | Cross-user visibility for assigned products | view product deliveries and product aggregate-report capability |
| `admin` | QC Tool and Django administration | all QC Tool capabilities; synchronized to Django staff access |

The authorization vocabulary also reserves region/product aggregate-report
permissions. No production aggregate-report view currently consumes them. A
future report must reuse the same capability-plus-scope policy rather than
treating the permission name as implementation.

Every newly created user receives `default`. Administrators can assign
additional roles and direct **Additional QC permissions** in Django Admin.
Direct permissions are additive and are the correct mechanism for a one-user
exception.

Canonical role permissions are synchronized by the application and are not
edited on the Group page.

## Capability plus scope

Cross-user visibility requires both a capability and a matching scope grant:

```text
visible delivery =
    own delivery
    OR administrator
    OR (region-view permission AND matching region grant)
    OR (product-view permission AND matching product grant)
```

- Product grants use canonical product-definition identifiers.
- Region grants currently store exact, opaque AOI codes.
- The current delivery-region resolver still reads the uploader's legacy
  profile country. `Delivery.aoi_code` now exists, but remains reported
  metadata until every supported product has authoritative spatial AOI
  validation; see [AOI metadata](aoi-metadata.md).
- A grant without its permission is inert.
- A permission without a grant is inert.

Managers may read cross-user records in scope. Mutation remains owner-or-admin
unless a specific policy explicitly changes that rule.

## Request-time behavior

Django stores identity—not QC permissions—in the session. On every request,
`AccountAccess` resolves current roles, direct/group permissions, product
grants, and region grants, then caches that immutable snapshot only on the
request object. Admin changes therefore take effect on the user's next request
without requiring logout.

## Adding a protected endpoint

1. Add a named URL through `protected_path` in the appropriate `urls/` module.
2. Add the matching policy to `access/routes/private.py` or, after an explicit
   security review, `public.py`.
3. Require a stable `AccountPermission`; never name a group in the view.
4. Load the object and call the delivery/job access policy before rendering,
   returning data, or mutating state.
5. Use a service for validation and multi-step writes.
6. Add route-matrix, permission, object-access, CSRF, and method tests.

Public is an allowlist. “It is only JSON” or “the link is hidden” is never a
reason to omit authentication or server-side authorization.
