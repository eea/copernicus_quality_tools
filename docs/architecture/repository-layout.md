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
│   ├── frontend/
│   │   ├── accounts/         # Identity, roles, permissions, grants, admin
│   │   ├── dashboard/        # Deliveries, jobs, UI, route and object access
│   │   ├── settings.py       # Environment-driven Django configuration
│   │   ├── urls.py           # Root URL composition
│   │   └── wsgi.py           # Gunicorn/Django entrypoint
│   ├── worker/               # Queue polling and job execution adapters
│   ├── aoi/                  # Shared canonical AOI identifier contract
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
├── migrations/        # Accounts schema and canonical permission seed
├── models/            # Capability and scope-grant models
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
├── services/
│   ├── api/           # Stable JSON request handling
│   ├── aoi/           # AOI persistence, projection, artifact backfill
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
├── models.py          # Delivery, Job, S3Info, and legacy account tables
└── views.py           # HTTP adapters; domain logic should move to services
```

When a view grows, extract one logical use case into a focused service rather
than creating another general helper module.

## Worker and shared security packages

The worker's scheduler, dispatcher, job contracts, and S3 materialization are
under `src/qc_tool/worker/`. Reusable trust-boundary behavior is intentionally
outside raster/vector QC modules:

- `aoi/` normalizes external AOI aliases without product dependencies;
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
