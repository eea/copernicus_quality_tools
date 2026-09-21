---
title: Administration
parent: User guide
nav_order: 2
---

# Administration

Administrators use `/admin/` for accounts and the dashboard configuration
pages for operational data. Django Admin requires an active staff user; the QC
Tool `admin` role synchronizes staff status.

## Add products

New installations have an empty product catalog. Open **Products → Upload
specification** and add the reviewed JSON specifications your users need.
Bundled recipe files do not appear automatically. A product becomes available
for assignment and QC after it is added successfully.

See [Product specifications](../development/product-definitions.md#add-or-update-a-product-in-the-browser)
for validation, revisions, and delivery-plan approval.

## Create a user

1. Open **Django Admin → Authentication and Authorization → Users**.
2. Select **Add user**.
3. Enter username and a strong password.
4. Save and continue editing.
5. Assign one or more **Product grants** for the products the user will work on.
6. Assign additional roles or direct permissions as needed.

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
| `default` | Work with own deliveries and jobs for assigned products; automatically retained |
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
- grant `view_product_deliveries` plus Product grants without assigning the
  complete product-manager role.

Cross-user scope permissions and scope rows are independent. Both are required.

## Product grants

Administrators assign products in **Django Admin → Users → Product grants**.
Both default users and product managers may have one or many grants, selected
from active catalog products or their registered QC definitions. The **Product
or QC definition** selector accepts either scope; add one row per assignment.
An exact QC-definition assignment grants only that definition, not its sibling
definitions. Identifiers use their canonical lowercase form; assigning one
product does not grant other products in the same family.

A catalog-product assignment covers its recorded releases. QC choices include
definitions associated with one unambiguous current release of that product;
shared definitions require an explicit definition assignment for execution.

A default user can upload deliveries, run QC jobs, and submit their own
successful deliveries for review within those assigned products. Grants do not
give access to another user's deliveries or permission to approve or decline
submissions. The product-manager role adds its existing cross-user access and
review capabilities within the assigned scope. Only administrators can assign
or remove users' product grants.

A non-administrator with no product grants cannot start product work. Assign
products to existing default users before they resume work. Administrators
retain access to every product.

Removing the last matching product grant takes effect on the user's next request, including
access to previous jobs, submission feedback, and retained submission files
for that product. Records remain available to assigned reviewers and
administrators.

Personal API tokens retain the scope captured when issued. Issue a new token
to use newly assigned products; revocations also restrict existing tokens.

If definitions are unavailable, Admin fails closed: existing unavailable
values remain visible/deletable, while new or changed grants are rejected.

## Bulk submission review

Assigned product managers and administrators can approve several deliveries
from **Products → Submission review**. Select eligible rows, or select all
eligible deliveries on the current page (up to 30), then choose **Approve
selected**. Check the selection, optionally add feedback shared with each
uploader, and confirm approval. Each submission keeps its own review history.

Competing submissions require an individual decision. If any selected submission
changes or becomes ineligible, the whole batch stops without approving any of
the selected deliveries. Return to the list to review the updated selection.
Bulk approval does not mark the product ready.

## Product readiness

The administrator approves the required product units in the delivery plan.
Assigned product managers review the users’ deliveries. When every required
unit has an accepted delivery, an assigned manager or administrator opens the
product and selects **Mark product ready**. Full coverage alone does not perform
this final action. Changes to the scope or acceptance decisions clear readiness
so the revised product must be confirmed again.

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

The **Boundaries** navigation is shown to administrators, product managers,
and users with `manage_configuration`. Default users work through Deliveries
without a separate boundary page in their navigation. Authenticated delivery
viewers retain read access to the active package; replacing it requires
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
