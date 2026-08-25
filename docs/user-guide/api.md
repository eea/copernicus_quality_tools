---
title: API
parent: User guide
nav_order: 3
---

# API automation

The API documentation and OpenAPI schema are intentionally public:

- `/api/`
- `/api/openapi.json`

All operational API endpoints are private and require both a valid personal
access token and the declared Django permission.

## Create a personal access token

1. Sign in through the browser.
2. Open **Profile → Settings**.
3. In **Personal API tokens**, enter a descriptive name and your current
   password, then select **Create token**.
4. Copy the value immediately; it is shown only once.
5. Store it in a secret manager.

QC Tool stores a SHA-256 digest of a cryptographically random token, not the
raw value. It cannot recover a lost token; create a replacement and delete the
old record instead. Use a separate named token for each client or integration.

## Authenticate

```bash
export QC_TOOL_API_TOKEN='<one-time-issued-secret>'

curl --fail-with-body \
  --header "Authorization: Bearer ${QC_TOOL_API_TOKEN}" \
  --header 'Accept: application/json' \
  http://localhost:8000/api/delivery-list
```

Never place tokens in query strings, command-line examples committed to
Git, screenshots, issue attachments, or URLs. Configure proxies and application
logging to redact the `Authorization` header. Use TLS outside a private local
development environment.

## Authorization

Each token captures the user's roles, permissions, product/region grants, and
administrator status when it is created. Effective access is the intersection
of that snapshot and the user's current live access. Revoking current access
therefore narrows existing tokens immediately; later grants do not broaden an
older token. Ownership and active-user checks still apply. A token is not an
independent superuser credential.

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

## Replacement and revocation

Users can keep multiple named tokens. To replace a token without interrupting
automation, create a new named token, update the client, verify it, and then
delete the old token. Deleting one token takes effect on the next request and
does not affect the user's other tokens.
