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
├── scripts/                   # Maintainer and data-preparation utilities
├── src/qc_tool/
│   ├── database/             # Whole-app migration history, policy, CLI and tests
│   ├── frontend/
│   │   ├── accounts/         # Identity, roles, permissions, grants, admin
│   │   ├── dashboard/        # Deliveries, jobs, UI, route and object access
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

## Frontend accounts app

```text
frontend/accounts/
├── admin/             # User, role, product, and region Admin composition
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

## Frontend dashboard app

```text
frontend/dashboard/
├── access/
│   ├── deliveries.py  # Delivery ownership/product/region read policy
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

```text
database/
├── README.md          # Ownership, layout and entry points
├── SCHEMA.md          # Canonical table ownership and persistence boundaries
├── MIGRATIONS.md      # Canonical whole-app migration and deployment runbook
├── policy.json        # Draft/released lifecycle and baseline identities
├── policy.py          # Policy loading and validation
├── deployment.py      # Planning, migration checks, apply and PostgreSQL locks
├── apps.py            # Django management-command discovery
├── management/        # database plan|check|apply command
├── migrations/
│   ├── accounts/      # Migration namespace for the accounts app label
│   └── dashboard/     # Migration namespace for the dashboard app label
├── checks/            # Git history guard and disposable schema verification
└── tests/             # Host history tests and runtime integration tests
```

The [application schema](../../src/qc_tool/database/SCHEMA.md) maps business
responsibilities to explicit table names and model modules. Accounts owns its
profiles and tokens as well as grants; dashboard discovers the other business
models. Table prefixes identify domains within one application database and do
not introduce independent component releases.

During draft, Django builds all tables from current models; migration history
is disabled and no first-party migration definitions exist. Model/app ownership
may evolve with the architecture. The first snapshots are generated at explicit
release freeze into this package's subdirectories for the then-current app
labels. Released deployments apply one complete graph, including Django's own
migrations. Legacy data transfers use a separate import procedure into a fresh
released database. See the
[migration policy](../development/database-migrations.md) for the developer,
freeze, data-transfer and deployment procedures.

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

`product_definitions/` and the `raster/` and `vector/` packages define domain
behavior. Treat changes there as separate product/QC work: document the
specification, use representative fixtures, and run the relevant domain tests.
Do not mix those changes into account, deployment, or generic security
refactors.
