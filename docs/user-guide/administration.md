---
title: Administration
parent: User guide
nav_order: 2
---

# Administration

The shared Admin navigation groups tasks into four sections:

- **Overview** shows administration tasks and the maintenance status.
- **User management** provides account creation, editing, role groups,
  permissions, product access and user-profile import/export.
- **Database** provides connected-record import/export, full PostgreSQL backups,
  restore and switch controls, schema checks, maintenance and a table browser.
- **Storage** browses retained delivery ZIPs, QC job files and published artifacts
  directly from the server, including files without database records.

Actions appear only with the required permissions. QC Tool administrators can
use all four sections. Staff with specific account permissions see the user or
group actions they have been granted; they do not gain database transfer or file
management authority. A product-manager role alone exposes no Admin controls.

The Admin header starts with the **Back to workspace** arrow, followed by the
plain **CLMS QC Tool | Admin** name. It uses a compact text identity; the
Copernicus and Land Monitoring logos remain in the workspace. The account menu
follows the workspace's menu pattern, with shared button styles.

Use the back arrow to leave administration deliberately. Admin task links,
sign-in and automatic recovery destinations remain inside Admin.

QC execution, specification uploads, boundaries and submission review belong to
the separate QC workspace. The Admin overview has no product shortcuts, setup
guide or general model directory.

The maintenance status distinguishes normal operation, stopping QC work, a ready
pause and a transfer in progress. Unreadable status does not claim that database
work is safe. Opening the overview does not poll workers, change maintenance state
or start an operation.

## Maintenance mode

Open **Admin → Database → Maintenance** and select **Turn on maintenance** to pause changes
and interrupt queued/running QC jobs. During **Turning on maintenance**, the
page automatically checks that application requests and QC work have stopped.
Wait for **Maintenance is on** before starting your database work. There is no
manual worker-check step. If stopping takes longer than usual, the page explains
what is happening; **Technical details** contains the diagnostic information.
With JavaScript disabled, use **Update progress** to complete the same checks.

Readiness covers participating QC Tool processes; it does not lock out direct
database clients or other external writers. A running transfer holds maintenance
until it completes or is recovered; use **View current transfer** from the
overview rather than trying to resume the service.

Use **Turn off maintenance** after the operator finishes. This becomes available
once QC work has stopped; a transfer must finish or be recovered first. Interrupted jobs
retain their history and must be submitted again; they do not restart automatically.

Signed-in users can continue browsing authorized pages, Admin records, exports
and retained files. A maintenance notification stays visible and controls that
change data are disabled. The server rejects uploads, QC requests, publication,
account changes and other mutations. Existing API credentials can read data.
Active QC Tool administrators and product managers can sign in during
maintenance through `/accounts/login/` or `/admin/login/`. Admin sign-in uses its
own Admin template with the same authentication and maintenance policies;
it does not grant additional account or database permissions. Ordinary users can
continue using existing valid sessions, but new sign-in is unavailable to them
until maintenance ends.

Maintenance sign-in uses a signed-cookie session lasting at most 30 minutes,
bound to the current maintenance generation while the mode is on. It expires
when maintenance ends or the generation changes. Signing in creates no database
session and does not update `last_login` or the stored password hash. If it expires during
maintenance, an eligible user can sign in again; an administrator can
return to the maintenance panel and turn the mode off after the operator has
finished. Product managers keep their existing scoped read access and cannot
control maintenance or Admin record transfers. All ordinary database-changing
actions remain blocked, including logout. Turning maintenance off succeeds
through the administrator's short session, then ends that authentication. On the
next request, accounts using maintenance sign-in must sign in normally through
the configured session backend before resuming ordinary operations. Existing
normal sessions keep their usual behavior.
After a reviewed database switch, an administrator's maintenance credential
remains bound to its original database so recovery stays available. Roles and
password hashes are rechecked there. Product-manager credentials from another
database are refused. During the same maintenance window, an administrator can
sign in against the immediately previous source if the selected copy is unavailable; this
fallback ends when maintenance resumes or its generation changes. The selected
database must have verified administrator access before reopening.
The [maintenance runbook](../deployment/maintenance.md)
documents command-line fallback for an inaccessible UI/database/state,
deployment requirements and backup boundaries.

Administrators use `/admin/` for accounts, database transfers and maintenance.
Operational product and delivery workflows remain in the QC workspace. Django
Admin requires an active staff user; the QC Tool `admin` role synchronizes staff
status.

## Manage database records

Open **Admin → Database → Browse database tables** (`/admin/database/?tables=1`).
**Find a table** accepts its friendly
name or PostgreSQL name, such as `account_api_token` or `catalog_product`. Filter
by area to narrow the directory. The directory covers the 24 current managed
tables, including framework and permission-assignment tables; unknown tables
are never opened through arbitrary SQL.

Choose a table to search and page through its records. **View record** shows
allowed stored fields and **Connected records**. Follow a linked field to its
parent, or a connection to the filtered dependent records. Sensitive password
hashes, token digests, session keys/payloads, private storage references and raw
import receipt summaries are excluded from this browser.

Available actions depend on the table:

| Records | Actions |
| --- | --- |
| Users | Create, edit profiles/access, or deactivate; existing usernames and hard deletion are protected |
| Role groups | Create/edit/delete custom groups; built-in QC roles remain protected |
| Product access | Create/edit/remove validated product grants; existing owner and creator are retained |
| API tokens | Inspect captured access and revoke one token after confirmation; secrets are issued only through the owner workflow |
| Products | Edit name and description with stale-edit detection; identity, specifications, activation and readiness remain protected |
| Permission assignments | Edit through the linked user or group form |
| QC runs, deliveries, revisions, publication history, receipts and framework identities | Inspect records and relationships; lifecycle changes use their existing service workflows |

These restrictions preserve dependencies outside SQL too: usernames locate
delivery ZIPs, job identities locate results, and published manifests retain
original record identities. Protected records cannot be overwritten or removed
through a forged form or bulk action. The last active administrator with usable
password sign-in cannot be deactivated, stripped of administrator authority or
have password sign-in disabled until another usable administrator exists.

The **Maintenance** card shows the current state and **Turn on maintenance** or
**Turn off maintenance**. Controls use the existing maintenance workflow and
generation checks; turning on follows QC shutdown progress. Imports/transfers
can keep maintenance on until completion or recovery. Browsing remains available
while maintenance blocks all ordinary record edits, creation and deletion.

## Import and export records

Choose the information you need from its owning section:

- **User management → Import users / Export users** handles account profiles.
  Export every profile or choose
  specific users. During import, create a new inactive account, use an existing
  account unchanged, **Update profile**, or skip an incoming user. The comparison
  shows incoming and existing first name, last name and email. **Update profile**
  changes only those three fields; passwords, activation, permissions, product
  access and history stay unchanged.
- **Database → Import records / Export records** handles the supported connected QC dataset:
  products, deliveries, jobs, review history, required user profiles and available
  local files. Import adds new records and resolves matching identities; it does
  not merge arbitrary PostgreSQL tables or overwrite existing QC records.

Uploading checks the package type. If it belongs to another section, the page
explains the change and opens that section before any import. Review account
identities, record conflicts and delivery-file availability, then use **Save
choices and review**. Confirm the updated review before **Import selected users**
or **Add records**. Export reviews and import execution require maintenance
**ready**; packages can be uploaded beforehand.

Use **Database → Full database backup** for a full native PostgreSQL backup or
restoring a separate database. Recovery pages also provide database-switch controls. Full backups preserve stored
credentials and permissions; the user and QC-record packages exclude them.
A completed restore offers **Review database switch** before the separate
**Switch active database** confirmation. **Database settings & rollback** keeps
the active database and eligible switch-back controls available within recovery.

Record imports require the supported model contract. They never alter a schema
or silently accept version drift. See the [record transfer guide](record-transfers.md)
for selection, private packages, recovery, compatibility and backup boundaries.

## Browse retained server files

Open **Admin → Storage** (`/admin/storage/`) and choose **Delivery uploads**,
**QC job artifacts** or **Published submissions**. Open folders, search names in
the current folder, then open a file to download it and inspect its database
links. Listings read the configured server directories rather than a list of
delivery rows, so files remain discoverable after a fresh database installation.
Private credentials, maintenance/transfer state, symbolic links and special files
are excluded. Published submissions are read-only.

Job and delivery record details include **Server files** links to their exact
expected locations. For a retained ZIP, **Verify ZIP against linked jobs** reads
its complete bytes and compares SHA-256 and recorded size to the linked runs.
A matching filename alone does not establish that it is the input used by an
old job. Database rows alone cannot recreate absent files; portable record
packages can include available retained files. Historical inputs without valid
recorded evidence remain unverified. Existing job downloads keep their checksum
and provenance checks.

To remove an unreferenced file from its normal location, open its details, turn
on maintenance, review the file, type its name and choose **Move file to trash**.
Linked files, original specifications and published evidence are protected.
Trash is recoverable and uses a private journal in the same storage area; this
interface never permanently purges files. **Trash → Restore file** returns the
file to its original path and never replaces an existing file. If records were
imported after a ZIP entered trash, restoration additionally checks their
recorded checksum and size before publishing it. Maintenance must be ready and
active database transfers must finish before either operation. File operations
write no application database records.

The browser manages local configured storage, not arbitrary server paths or S3
buckets. Keep these directories mounted and backed up separately from PostgreSQL.

## Check schema compatibility

Use **Database → Schema & migrations → Check database schema** for a read-only
comparison with the current models. QC Tool v3.0.0 uses a draft, model-based
schema; it does not offer in-place schema migrations. A partial, outdated or
foreign schema is refused without repair. A future migration-managed release
requires its separately reviewed initialization/adoption procedure. See
[database policy](../development/database-migrations.md).

## Add products

New installations have an empty product catalog. Open **Products → Upload
specification** and add the reviewed JSON specifications your users need.
Bundled recipe files do not appear automatically. A product becomes available
for assignment and QC after it is added successfully.

See [Product specifications](../development/product-definitions.md#add-or-update-a-product-in-the-browser)
for validation, revisions, and delivery-plan approval.

## Create a user

1. Open **Admin → User management**.
2. Select **Create user**.
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

Administrators assign products in **Admin → User management → Product access**.
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
