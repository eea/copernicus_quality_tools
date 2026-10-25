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
│   ├── database/             # Models-only initialization, validation and tests
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
│   ├── product_units.py      # Canonical product-unit identifiers and legacy adapters
│   ├── aoi/                  # Legacy geographic identifier contract
│   ├── worker_auth/          # Shared WorkerToken header contract
│   ├── archive_security/     # Bounded no-traversal ZIP extraction
│   ├── product_security/     # Safe product identifier/definition loading
│   ├── s3_security/          # Canonical S3 endpoint allowlisting
│   ├── raster/               # Raster QC implementations
│   ├── vector/               # Vector QC implementations
│   ├── common.py             # Shared configuration and job artefact helpers
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
│   ├── boundaries/    # Validated immutable boundary generations
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

Version 3.0.0 contains no migration framework, definitions, initial snapshots or
legacy converter. Current Django models define the whole application schema.

```text
database/
├── README.md          # Ownership, models-only policy and entry points
├── SCHEMA.md          # Canonical table ownership and persistence boundaries
├── TABLES.md          # Table, column, constraint and index reference
├── MIGRATIONS.md      # Current initialization/validation runbook
├── MANUAL_RESTORE.md  # Restore a privately prepared current-schema artifact
├── policy.json        # Models-only source contract
├── policy.py          # Policy validation and disabled Django migration modules
├── deployment.py      # Empty-target initialization and read-only validation
├── apps.py            # Django management-command discovery
├── management/        # database plan|check|apply command
├── checks/            # Source-contract gate and disposable schema verification
└── tests/             # Source-contract and runtime integration tests
```

The [application schema](../../src/qc_tool/database/SCHEMA.md) maps business
responsibilities to explicit table names and model modules. Accounts owns its
tokens and product grants; dashboard discovers the other business models.
Table prefixes identify domains within one application database and do not
introduce independent component releases.

`database plan|check` inspects the schema read-only. `apply` initializes an
entirely empty database and leaves a complete matching one unchanged; partial or foreign schemas and
detected model drift are refused. Model changes require a separate target,
not automatic alteration of an existing database. Legacy database conversion is
private manual work outside the codebase. See
[Database initialization](../development/database-migrations.md) and the
[manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md).

Initial migration definitions may be introduced only in a separately reviewed
3.0.1-or-later release with an explicit existing-database transition plan.

## Worker and shared security packages

The worker's scheduler, dispatcher, job contracts, and S3 materialization are
under `src/qc_tool/worker/`. Reusable trust-boundary behavior is intentionally
outside raster/vector QC modules:

- `product_units.py` normalizes business identifiers and adapts legacy AOI metadata;
- `archive_security/` validates resource limits and paths before extraction;
- `product_security/` validates product identifiers and definition files;
- `s3_security/` canonicalizes and allowlists exact HTTPS origins;
- `worker_auth/` owns the Authorization header format;
- `worker/aoi/` adapts generic naming captures to canonical result metadata;
- `worker/s3_delivery/` separates client construction, transfer, storage,
  hashing, policy, and orchestration.

## Product and QC ownership

`product_definitions/` and the `raster/` and `vector/` packages define QC
behavior. Keep raster and vector algorithms, check-specific parameters and result
semantics with their checks. Consume original specification bytes without
rewriting specifications or uploaded snapshots.

Reusable execution infrastructure belongs outside the check packages:

- `worker/inspire.py` owns the INSPIRE service client, polling deadlines and
  metadata-validation orchestration shared by raster and vector checks;
- `worker/documents.py` owns shared PDF discovery and readability checks;
- `worker/archives.py` owns the shared worker archive preparation adapter.

The corresponding integration entry points remain thin adapters to these shared
services and retain their check identities and parameter contracts. Compatibility
exports in `vector/helper.py` support existing integrations; new reusable code
should import its owning worker module directly. Worker, frontend, database and maintenance
infrastructure must not statically import raster/vector check implementations.
The dispatcher may still load a configured check dynamically when executing a
product recipe.

Verify refactors with representative fixtures and the relevant domain tests.
`test_worker_module_boundaries.py` enforces the static dependency direction.
