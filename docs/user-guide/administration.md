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

The delivery-side region value is temporarily resolved from the uploader's
legacy profile country. Do not treat that field as the final generalized AOI
model.

## Deactivate instead of delete

User deletion is disabled in QC Tool's User Admin. Clear **Active** to prevent
future authentication while preserving delivery and job history. Plan any
permanent erasure or ownership transfer as a deliberate retention workflow.

## API credentials

API credentials are user-owned and one-way hashed. Admin displays only whether
a credential is configured and can revoke it by deleting the inline record.
It cannot recover the secret.

The user issues or rotates a credential from the authenticated Deliveries page.
The raw value is shown once. Store it in a secret manager; rotating it
immediately invalidates the previous value.

## Boundary packages

The **Boundaries** and **Upload boundaries** pages require
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
