---
title: Repository layout
parent: Architecture
nav_order: 1
---

# Repository layout

The source tree is organized by ownership, not by HTTP page. This keeps
infrastructure changes separate from product recipes and QC algorithms.

```text
copernicus_quality_tools/
├── docker/                    # Images, Compose files, entrypoints, validator
├── docs/                      # This documentation site
├── documentation/             # Historical diagrams and reference artefacts
├── product_definitions/       # Product-specific JSON QC recipes
├── scripts/                   # Purpose-specific operator tools and host tests
├── src/qc_tool/
│   ├── database/             # Native migrations, schema inspection, backups and recovery
│   ├── frontend/
│   │   ├── accounts/         # Identity, roles, permissions, grants, admin
│   │   ├── dashboard/        # Deliveries, jobs, UI, route and object access
│   │   ├── admin_config.py   # Selects QCAdminSite through Django AdminConfig
│   │   ├── admin_site.py     # Account/database administration navigation
│   │   ├── templates/admin/ # Shared Admin shell, sign-in and error pages
│   │   ├── settings.py       # Environment-driven Django configuration
│   │   ├── urls.py           # Root URL composition
│   │   └── wsgi.py           # Gunicorn/Django entrypoint
│   ├── worker/               # Queue polling and job execution adapters
│   ├── jobs/                 # Framework-independent job IDs and pull contracts
│   ├── boundaries/           # Shared boundary types, layout and pinned readers
│   ├── storage/              # Runtime path ownership, mount guards, scratch retention
│   ├── product_units.py      # Canonical product-unit identifiers and legacy adapters
│   ├── aoi/                  # Legacy geographic identifier contract
│   ├── worker_auth/          # Shared WorkerToken header contract
│   ├── archive_security/     # Bounded no-traversal ZIP extraction
│   ├── product_security/     # Safe product identifier/definition loading
│   ├── s3_security/          # Canonical S3 endpoint allowlisting
│   ├── raster/               # Raster QC implementations
│   ├── vector/               # Vector QC implementations
│   ├── common.py             # Compatibility configuration and job artefact helpers
│   └── test/                 # Worker and QC tests
└── testing_data/              # Test fixtures
```

The [script catalog](../../scripts/README.md) separates maintained commands,
repeatable verification tests, manual diagnostics and historical experiments. Application commands and core regression tests remain with their
owning packages under `src/qc_tool/`.

## Frontend accounts app

```text
frontend/accounts/
├── admin/             # User/group administration and account-access inlines
├── authentication/    # Login backend and API credential authentication
├── authorization/     # Role, permission, and per-request access facts
├── management/        # User provisioning management command
├── models/            # Profiles, API tokens, capabilities and scope grants
├── services/          # User, role, and product-grant use cases
├── signals/           # Default-role and staff synchronization
├── templates/         # Account-specific pages and error fragments
├── tests/             # Account, auth, route, and admin tests
├── urls.py             # Login/logout/password/credential URLs
└── views/              # Password and API credential workflows
```

Rules:

- use Django's native `User`, `Group`, and `Permission` models;
- put reusable identity/capability facts here;
- do not import `Delivery` or `Job` into accounts;
- use services for creation and multi-model writes;
- keep credentials out of templates, logs, URLs, and Django Admin fields.

## Administration interface

Admin has four navigation sections: **Overview**, **User management**,
**Database** and **Storage**. User management owns account creation, groups,
permissions and profile transfers. Database owns connected-record transfers,
full backups/recovery, schema checks, maintenance and the curated table browser.
Storage inspects configured retained server files independently of SQL rows.
The overview links to these three task areas; section visibility follows permissions.

| Owner | Responsibility |
| --- | --- |
| `frontend/admin_config.py`, `admin_site.py` | Select `QCAdminSite`, derive account actions from Django model permissions, and provide permission-aware section context |
| `frontend/templates/admin/` | Shared Admin shell, navigation, sign-in and error templates |
| `frontend/dashboard/templates/dashboard/shared/brand.html`, `dashboard/static/dashboard/css/ui/brand.css` | Shared workspace/API/Admin identity with the Copernicus and Land Monitoring logos |
| `frontend/dashboard/static/dashboard/css/ui/actions.css` | Shared button primitives; each shell retains its own navigation destinations |
| `frontend/dashboard/static/dashboard/css/ui/navigation.css`, `js/shared/navigation.js` | Shared account-menu styling and native menu interaction, including Admin's Profile menu |
| `frontend/accounts/admin/` | Existing user/group forms, permissions, product-access and token inlines |
| `frontend/accounts/views/`, `frontend/urls.py` | Shared authentication policies and Admin-specific sign-in/logout/error presentation |
| `frontend/dashboard/templates/admin/` | Six-direction overview and user, boundary, notification, database, storage and maintenance pages |
| `frontend/dashboard/services/admin_navigation.py`, `templates/admin/includes/direction_card.html` | Permission-aware overview directions and one reusable card; task links are absent from the header |
| `frontend/dashboard/views/admin_notifications.py` | Administrator management of the existing file-backed workspace announcement |
| `frontend/dashboard/urls/boundaries.py`, `dashboard/views/boundaries.py` | Admin-only boundary catalog, replacement, data and export routes; reuse shared boundary services and UI components |
| `frontend/dashboard/views/admin_users.py` | Permission-filtered user-management landing page; reuses registered account editors and profile transfers |
| `frontend/dashboard/views/admin_data_transfer.py` | HTTP forms and review presentation; database operations remain in `database/transfers/` |
| `frontend/dashboard/views/admin_maintenance.py`, `dashboard/services/maintenance/` | Explicit maintenance actions, progress and shared writer admission |
| `frontend/dashboard/services/maintenance/barrier.py` | Shared ready-state, generation and exclusive activity barrier for transfers and storage mutations |
| `frontend/dashboard/views/admin_storage.py`, `dashboard/services/storage_admin/` | Confined file browsing/download, exact database-reference checks and reversible journaled trash/restore |

`QCAdminSite` disables the general model sidebar and Django's automatic site
link. Task navigation and automatic authentication/error recovery destinations
stay in Admin; its brand links to the Admin overview. One explicit back-arrow
**Back to workspace** control leads the header and lets the user deliberately
switch interfaces. It precedes the shared logos and **CLMS QC Tool | Admin**
identity. The account menu follows the workspace's menu pattern; Admin uses the
light theme. Its responsive menu holds account controls; the overview owns task
discovery. Boundary package and notification management belong to Admin.
Do not add other workspace shortcuts, a product setup guide, delivery
or submission-review cards, or an unrestricted model directory. Those operational
workflows belong to the separate QC workspace. Reuse shared navigation/button
primitives without importing workspace operational navigation or controls into
Admin.

Filtering `get_app_list()` changes navigation only. Existing domain ModelAdmin
registrations and direct-route permissions remain intact. Staff see only their
granted user/group actions; the product-manager role alone exposes no account
or database controls. Database transfers and maintenance still require the QC
administrator role. Admin-specific templates reuse authentication and maintenance
policies rather than implementing a second authentication system.

Storage exposes only configured incoming uploads, recognized QC job namespaces
and published submissions. Descriptor-relative opens reject traversal, symlinks,
hard-linked files, special files and overlaps with private control/credential
storage. Browsing does not rely on Delivery/Job rows. Historical ZIP verification
uses exact record paths and recorded checksum/size; it never searches for a
substitute with a similar filename. Existing job-download provenance checks are
reused unchanged. Removing an unreferenced file requires ready maintenance and
a reviewed file fingerprint; it moves to same-filesystem private trash with a
durable intent journal. Restore never overwrites a destination. If incoming ZIP
records were subsequently imported, restore verifies the private payload against
their recorded checksum and size. Published files/specifications are immutable.
These filesystem operations do not add schema or application database writes.

## Frontend dashboard app

```text
frontend/dashboard/
├── access/
│   ├── deliveries.py  # Delivery ownership/product read policy
│   ├── jobs.py        # Job access inherited from its delivery
│   └── routes/        # Complete public/private endpoint registry
├── domain/            # Catalog, delivery, job, storage and publication models
├── services/
│   ├── api/           # Stable JSON request handling
│   ├── product_units/ # Product unit persistence, projection, artifact backfill
│   ├── artifacts/     # Confined downloads and attachments
│   ├── boundaries/    # Admin boundary upload/activation; shared reader compatibility
│   ├── configuration/ # Announcement/configuration use cases
│   ├── exports/       # Spreadsheet generation
│   ├── jobs/          # Job request parsing and serialization
│   ├── s3/            # Frontend S3 registration inspection
│   └── uploads/       # Delivery and resumable-upload storage
├── static/            # Self-hosted browser assets
├── templates/         # Django templates
├── urls/              # Pages, data, API, and worker URL groups
├── models.py          # Model discovery and stable imports; dashboard app label
└── views.py           # HTTP adapters; domain logic should move to services
```

When a view grows, extract one logical use case into a focused service rather
than creating another general helper module.

## Application database package

`src/qc_tool/database/` owns all first-party database lifecycle assets:

The current 3.0.0 includes migration management. Committed native Django migrations
define history, current models describe the installed schema, and the central
package coordinates safe candidate upgrades with database/file recovery.
Earlier history-free 3.0.0 installations remain an explicit strictly supported
source; their application version alone does not establish schema compatibility.

```text
database/
├── README.md          # Ownership, managed policy and entry points
├── SCHEMA.md          # Model ownership and persistence boundaries
├── TABLES.md          # Stored-field reference and dated physical evidence
├── MIGRATIONS.md      # Initialization, candidate upgrades and recovery runbook
├── MANUAL_RESTORE.md  # Restore a separately prepared native artifact
├── policy.json        # Managed release and reviewed adoption target graph
├── policy.py          # Strict policy validation
├── deployment.py      # Empty initialization and stable schema lock
├── schema/            # Shared read-only catalog/field/constraint inspection
│   └── strict/        # Exact supported-source checks, backend defaults and objects
├── migration_engine/  # Django graph, historical schema and candidate execution
├── migrations/        # Central app's committed native migration history
├── upgrades/          # Backup → candidate → migration → explicit switch
├── transfers/         # Native/portable backups, journals, ownership and file pins
├── management/        # Whole-application database plan|check|apply command
├── checks/            # Source gate and disposable schema verification
└── tests/             # Source, initialization, upgrade and recovery regressions
```

The [application schema](../../src/qc_tool/database/SCHEMA.md) maps business
responsibilities to explicit tables and modules. Accounts owns tokens and grants;
dashboard discovers other domain models. Their conventional `migrations/`
packages and `qc_database` share Django's graph and recorder. Domain table
prefixes do not introduce independent database releases.

`database plan|check` inspects schema/history read-only. `apply` initializes an
entirely empty database and leaves a current managed target unchanged. Supported
upgrades migrate an operation-owned restored candidate, verify SQL and retained
file identities, then require an explicit switch. Unknown drift/history is
refused. Startup never applies pending migrations. Legacy conversion stays
private manual work outside the codebase. See [Database migrations](../development/database-migrations.md)
and the [manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md).

## Small modules and shared ownership

Prefer cohesive production Python modules below 150 lines. Split a growing file
when it combines responsibilities; keep released migration files and cohesive
declarations intact. A package should make its entry points easy to find, with
explicit imports and no dynamic forwarding or copied implementation behind a
compatibility layer.

The migration administration workflow follows these boundaries:

| Owner | Responsibility |
| --- | --- |
| `dashboard/views/admin_migrations/` | HTTP endpoints and action dispatch, one journey decision, presentation and request-local page context |
| `dashboard/templates/admin/migration_panels/` | Named page panels using the shared Admin shell, forms and transfer progress controls |
| `database/schema/` | Reusable read-only inspection of fields, keys, indexes and catalog objects |
| `database/schema/strict/` | Exact source recognition, extra-object rejection and backend default/generated-expression checks |
| `database/deployment.py` | Explicit empty-target initialization and the unchanged application-wide schema lock |
| `database/migration_engine/` | Django graph/history, fingerprints, supported-source recognition and owned candidate execution |
| `database/upgrades/` | Backup review, source/candidate connections, storage evidence, execution receipts, verification and recovery |
| `accounts/services/actors.py` | One username snapshot contract for job and submission audit records |

Initialization reuses the same schema inspector as readiness and historical model
validation. Upgrade review and execution reuse backup coverage, package identity
and storage evidence helpers. HTTP handlers use the existing account-owned private
response-cache policy; they do not implement a second database or recovery engine.
Keep authorization and durability policies with their owners when extracting
helpers, even when two implementations look superficially similar.

## Remaining refactoring priorities

The codebase still has large modules outside these boundaries. The next useful
changes are responsibility splits with regression coverage, rather than moving
unchanged blocks into anonymous utilities:

| Priority | Current owner | Boundary to establish |
| --- | --- | --- |
| 1 | `database/transfers/service.py` | Separate admission, snapshots/capacity, operation lifecycle and native/portable runners; replace cross-package private calls with owned capabilities before splitting callers |
| 2 | `dashboard/views/admin_data_transfer.py` | Split its combined HTTP action/render handler into actions, page context and presentation; reuse the existing transfer service and Admin cache policy |
| 3 | `database/transfers/artifacts.py` | Separate inventory, package validation, conflict inspection and restore writes while retaining one artifact path/reference contract |
| 4 | `database/transfers/postgres.py` | Separate connection/tooling, catalog inventory, capture, owned target creation and restore; preserve fingerprint ordering and restore admission |
| 5 | `worker/scheduler.py` | Separate maintenance admission, HTTP transport/routes, process lifetime and scheduling without weakening worker pause acknowledgement |

In particular, migration orchestration still calls private transfer/restore
functions. Small migration modules make that dependency visible; they do not
remove it. Extract the shared transfer capabilities into real owning modules and
test their consumers together. Forwarding wrappers that merely rename private
functions would conceal the dependency rather than simplify it.
