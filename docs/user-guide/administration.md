---
title: Administration
parent: User guide
nav_order: 2
---

# Administration

Administrators use `/admin/` for accounts and the dashboard configuration
pages for operational data. Django Admin requires an active staff user; the QC
Tool `admin` role synchronizes staff status.

## Create a user

1. Open **Django Admin → Authentication and Authorization → Users**.
2. Select **Add user**.
3. Enter username and a strong password.
4. Save and continue editing.
5. Assign roles, direct permissions, and optional grants.

Every newly created user automatically receives the `default` role. There is no
public registration.

For an initial production superuser, use the interactive management command:

```bash
docker compose -f <deployment-compose.yml> exec frontend \
  python3 -m qc_tool.frontend.manage createsuperuser
```

## Roles

| Role | Use |
| --- | --- |
| `default` | Baseline application access; automatically retained |
| `product_manager` | Product-scoped cross-user read/report capabilities |
| `admin` | All QC capabilities and Django Admin access |

Canonical roles cannot be renamed or deleted through Admin. Their permission
bundles are synchronized by QC Tool.

## Direct user permissions

The **Additional QC permissions** field grants a capability to one user in
addition to their roles. It intentionally lists only QC Tool capability
permissions, not Django's unrelated model permissions.

Examples:

- grant `manage_configuration` to a trusted operator without giving full Admin;
- grant `view_region_deliveries` plus one or more Region grants to a default
  user;
- grant `view_product_deliveries` plus Product grants without assigning the
  complete product-manager role.

Scope permissions and scope rows are independent. Both are required.

## Product grants

Product grants are selected from currently available product definitions. A
product manager may have one or many. The product identifier is stored in
canonical lowercase form and matched to a delivery's product.

If definitions are unavailable, Admin fails closed: existing unavailable
values remain visible/deletable, while new or changed grants are rejected.

## Region grants

Region grants currently store exact opaque AOI codes and do not normalize or
validate against a catalogue. Each value is unique per user. Assign the related
Additional QC permission separately.

The delivery-side region value is still resolved from the uploader's legacy
profile country. Jobs and deliveries now record canonical AOI reporting
metadata, but it is not an authorization fact until every supported product
has authoritative spatial validation. See
[AOI metadata](../architecture/aoi-metadata.md) for that trust boundary.

## Deactivate instead of delete

User deletion is disabled in QC Tool's User Admin. Clear **Active** to prevent
future authentication while preserving delivery and job history. Plan any
permanent erasure or ownership transfer as a deliberate retention workflow.

## Personal API tokens

Personal API tokens are user-owned and one-way hashed. A user can create
multiple named tokens from **Profile → Settings**, use a separate token for
each integration, and delete either token without interrupting the others.
Django Admin displays only non-secret token metadata and can revoke a token by
deleting its record. It cannot recover the secret.

The raw token is shown once after creation. Store it in a secret manager. Each
token captures the user's permissions and scopes when it is created; effective
API access is the intersection of that snapshot and the user's current access.
Removing a live permission therefore narrows existing tokens immediately,
while later grants require a new token.

## Boundary packages

Authenticated delivery viewers can inspect the active package on
**Boundaries**. Replacing the package remains restricted to users with
`manage_configuration`.

A boundary package must be a ZIP with this logical layout:

```text
package.zip
├── raster/
│   └── ... boundary files ...
└── vector/
    └── ... boundary files ...
```

The upload service validates archive paths, entry counts, sizes, compression
ratio, and root layout before publishing an immutable generation. Never edit a
published generation in place.

After activation, verify both boundary lists in the UI and run a representative
QC job. Retain older generations until no running job can reference them.
