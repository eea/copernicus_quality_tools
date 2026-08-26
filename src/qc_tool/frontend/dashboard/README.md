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
| Deliveries | `urls/deliveries.py` | `views/deliveries/` | `templates/dashboard/deliveries/` | `*/features/deliveries/` | `services/deliveries/`, `services/uploads/` |
| Products | `urls/products.py` | `views/products.py` | `templates/dashboard/products/` | `js/features/products/` | `services/products.py` |
| Boundaries | `urls/boundaries.py` | `views/boundaries.py` | `templates/dashboard/boundaries/` | `*/features/boundaries/` | `services/boundaries/` |
| QC jobs | `urls/jobs.py` | `views/jobs.py` | `templates/dashboard/jobs/` | `js/features/jobs/` | `services/jobs/`, `services/aoi/` |
| API access | `urls/api_access.py` | `views/api_access.py` | `templates/dashboard/api_access/` | `*/features/api_access/` | `services/api/`, `services/s3/` |
| Configuration | `urls/configuration.py` | `views/configuration.py` | `templates/dashboard/configuration/` | `*/features/configuration/` | `services/configuration/` |
| Worker callbacks | `urls/workers.py` | `views/workers.py` | — | — | worker services |

Shared layouts and partials live in `templates/dashboard/layouts/` and
`templates/dashboard/shared/`. Shared design primitives live in `css/ui/`.
Third-party browser code lives in `js/vendor/`; do not split or edit vendored
files as if they were application components.

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
   `pages.py`, `listing.py`, `actions.py`, and `files.py` pattern.
3. Put reusable rules in `services/<feature>/`, with contracts and errors in
   separate modules when they form stable boundaries.
4. Keep templates and first-party CSS/JavaScript under the same feature name.
5. Add focused feature tests, then run the frontend regression suite documented
   in `docs/development/testing.md`.
