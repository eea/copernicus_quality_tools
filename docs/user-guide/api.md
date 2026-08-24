---
title: API
parent: User guide
nav_order: 3
---

# API automation

The API documentation and OpenAPI schema are intentionally public:

- `/api/`
- `/api/openapi.json`

All operational API endpoints are private and require both a valid API
credential and the declared Django permission.

## Issue a credential

1. Sign in through the browser.
2. Open the API credential section on Deliveries.
3. Select **Issue/rotate credential**.
4. Copy the value immediately; it is shown only once.
5. Store it in a secret manager.

QC Tool stores a SHA-256 digest of a cryptographically random token, not the
raw value. It cannot recover a lost credential; rotate it instead.

## Authenticate

```bash
export QC_TOOL_API_CREDENTIAL='<one-time-issued-secret>'

curl --fail-with-body \
  --header "Authorization: Bearer ${QC_TOOL_API_CREDENTIAL}" \
  --header 'Accept: application/json' \
  http://localhost:8000/api/delivery-list
```

Never place credentials in query strings, command-line examples committed to
Git, screenshots, issue attachments, or URLs. Configure proxies and application
logging to redact the `Authorization` header. Use TLS outside a private local
development environment.

## Authorization

API credentials identify the same Django user as the browser session. Roles,
direct permissions, product/region grants, ownership, and active status still
apply. A token is not an independent superuser credential.

Read endpoints use the same delivery/job access policy as the browser. Mutation
endpoints require owner-or-admin behavior unless explicitly documented
otherwise.

## Response handling

| Status | Meaning |
| --- | --- |
| `200`/`201` | Request succeeded |
| `400` | Invalid request contract or identifier |
| `401` | Missing, malformed, revoked, or invalid credential |
| `403` | Authenticated user lacks capability or object scope |
| `404` | Resource does not exist or is not exposed by the endpoint |
| `405` | HTTP method is not allowed |
| `413` | Declared payload exceeds a configured limit |
| `502`/`503` | Bounded upstream service failure or unavailable configuration |

Protected API responses use private/no-store caching headers. Clients should
not persist credentials or sensitive response bodies in shared caches.

## Rotation and revocation

Rotation replaces the single credential immediately; there is no overlap
window. Coordinate dependent automation before rotating. Revocation removes the
credential record and takes effect on the next request.

The current schema supports one API credential per user. Create separate users
when independent automation principals or separate revocation boundaries are
required.
