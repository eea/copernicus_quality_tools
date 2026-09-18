# QC workspace application

`dashboard` is the historical Django application and database app label. It
owns the authenticated QC workspace as a whole; it is **not** the implementation
of the Dashboard home page. Renaming the Django app label would alter migration
history and content-type identities, so the label remains stable. The home page
is called **overview** in application code.

## Where to start

Each user-facing capability uses the same feature name across routes, views,
templates, browser assets, and services:

| Capability | Routes | Views | Templates | First-party assets | Domain services |
| --- | --- | --- | --- | --- | --- |
| Workspace overview | `urls/overview.py` | `views/overview.py` | `templates/dashboard/overview/` | `css/features/overview/` | `services/overview/` |
| Deliveries | `urls/deliveries.py` | `views/deliveries/` | `templates/dashboard/deliveries/` | `*/features/deliveries/` | `services/deliveries/`, `services/uploads/`, `services/submissions/` |
| Products | `urls/products.py` | `views/products/` | `templates/dashboard/products/` | `*/features/products/` | `services/products/`, `services/catalog/` |
| Boundaries | `urls/boundaries.py` | `views/boundaries.py` | `templates/dashboard/boundaries/` | `*/features/boundaries/` | `services/boundaries/` |
| QC jobs | `urls/deliveries.py`, `urls/jobs.py` | `views/jobs/` | `templates/dashboard/jobs/` | `*/features/jobs/` | `services/jobs/`, `services/product_units/`, `services/catalog/definitions.py` |
| API access | `urls/api_access.py` | `views/api_access/` | `templates/dashboard/api_access/` | `*/features/api_access/` | `services/api/`, `services/s3/` |
| Configuration | `urls/configuration.py` | `views/configuration.py` | `templates/dashboard/configuration/` | `*/features/configuration/` | `services/configuration/` |
| Worker callbacks | `urls/workers.py` | `views/workers.py` | — | — | worker services |

Shared layouts and partials live in `templates/dashboard/layouts/` and
`templates/dashboard/shared/`. Shared design primitives live in `css/ui/`.
Third-party browser code lives in `js/vendor/`; do not split or edit vendored
files as if they were application components. The page-layout, breadcrumb,
button, and CSS ownership contracts are documented in
[`templates/dashboard/README.md`](templates/dashboard/README.md).

## Browser URL hierarchy

Browser pages follow the workspace navigation rather than the historical
Django app-module layout. Canonical page URLs use a trailing slash:

```text
/
/deliveries/
  upload/
  jobs/new/
  jobs/<delivery_id>/
  job-result/<job_uuid>/
/products/
  list/                    authenticated JSON
  <product_ident>/         HTML product detail
/boundaries/
  upload/
/api/
```

The job-history identifier is a delivery primary key; the result identifier is
a job UUID. Keep static product children such as `products/list/` before the
dynamic `products/<product_ident>/` pattern. `list` is consequently a reserved
product identifier and is rejected when catalog data crosses into the system.
Product details render bounded, release-key-ordered current release streams so
multiple valid release series are never collapsed into one arbitrary record.

This hierarchy applies to human-facing pages. Stable transport, `/data/*`,
artifact, mutation, worker, and operational `/api/*` contracts keep their
existing paths and authentication behavior. Do not move an internal endpoint
just to make it resemble a page URL.

Authenticated redirects for superseded page bookmarks belong in
`urls/compatibility.py`. Each alias redirects directly to its canonical route,
preserves the query string, and is temporary; templates and application code
must always reverse the canonical route name. Never use compatibility routes
for API or mutation traffic.

## Catalog and submission lifecycle map

The normalized product/submission workflow is deliberately split by type of
decision so database rules, filesystem operations, and HTTP handling do not
grow into one service module:

| Concern | Owning module |
| --- | --- |
| Model aggregates and audit records | `domain/<aggregate>/` |
| Manifest parsing and definition validation | `services/catalog/manifest/` |
| Idempotent immutable catalog synchronization | `services/catalog/sync/` |
| Job definition/release snapshots | `services/catalog/definitions.py` |
| Product completion and remaining-product unit queries | `services/catalog/coverage/` |
| QC job creation and result persistence | `services/product_units/jobs/` |
| Browser QC job adapters | `views/jobs/` |
| Overview queries and section builders | `services/overview/sections/` |
| Delivery SQL planning and row projection | `services/deliveries/listing/query/` |
| Delivery JSON and spreadsheet presentation | `views/deliveries/listing/` |
| Local/S3 delivery API adapters | `views/api_access/deliveries/` |
| QC job API adapters | `views/api_access/jobs/` |
| Boundary archive validation and publication | `services/boundaries/archive/`, `services/boundaries/storage/` |
| Submission orchestration | `services/submissions/lifecycle.py` |
| Eligibility and row-locked reservation | `services/submissions/reservation/` |
| Publication database state transitions | `services/submissions/state/` |
| Storage paths, secure copying, and manifests | `services/submissions/publication/` |
| Duplicate candidates and manager decisions | `services/submissions/conflicts/` |
| Delivery mutation adapters | `views/deliveries/actions/` |
| Scoped catalog/review administration | `admin_features/catalog.py`, `admin_features/submissions/` |

`models.py` is only Django's model-discovery and compatibility boundary. Model
implementations belong in `domain/`; workflows belong in `services/`.

## Dependency direction

Keep dependencies flowing in this direction:

```text
urls -> views -> services/access -> models and infrastructure
                 |
                 -> immutable presentation contracts
```

- URL modules declare paths and route policy only.
- Views translate HTTP input/output and delegate domain decisions.
- Services contain reusable business rules, filesystem/database workflows,
  serialization, and bounded presentation queries.
- Templates do not own authorization decisions. Views pass server-derived
  capabilities and scoped data.
- A feature may use a shared service, but services must not import views.

`views/__init__.py` and `helpers.py` are compatibility export surfaces for old
imports. New code must import the owning module directly. They must stay thin
and contain no behavior.

## Adding or changing a feature

1. Add the route to the matching `urls/<feature>.py` module and classify it in
   the route-policy registry under `access/routes/`.
2. Put HTTP handling in the matching `views/` module. Split by responsibility
   before a module becomes difficult to scan; deliveries demonstrate the
   `pages.py`, `listing/`, `actions/`, and `files.py` pattern.
3. Put reusable rules in `services/<feature>/`, with contracts and errors in
   separate modules when they form stable boundaries.
4. Keep templates and first-party CSS/JavaScript under the same feature name.
5. Add focused feature tests, then run the frontend regression suite documented
   in `docs/development/testing.md`.
