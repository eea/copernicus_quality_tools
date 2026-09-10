---
title: Development
nav_order: 5
has_children: true
---

# Development

Use Docker as the canonical application environment. `pyproject.toml` is not a
complete frontend or worker dependency declaration: the supported frontend
graph is pinned in `docker/requirements.frontend.txt`, while the worker image
contains compiled geospatial, database, Java, and validator dependencies.

## Change workflow

1. Read the relevant [architecture](../architecture/index.md) section.
2. Start the [local environment](../getting-started/index.md).
3. Keep the change in the owning package; database changes follow the
   [application-wide release policy](database-migrations.md). Follow the workflow
   for its phase: model changes without migration files in `draft`, reviewed
   forward migrations in `released`.
4. Add focused tests for the behavior and trust boundary.
5. Run the focused suite while iterating.
6. Run the documented regression suite and checks before review.
7. Update documentation and environment-variable reference in the same change.

## Architectural expectations

- HTTP views adapt requests and responses; they do not own reusable business
  logic.
- Services implement one named use case and expose typed results/errors.
- Account capabilities use Django permissions, not group-name conditions.
- Domain object access is centralized under `dashboard/access/`.
- Every named dashboard URL is classified in the public/private registry.
- User input is parsed before it reaches filesystem, SQL, subprocess, archive,
  or network operations.
- Multi-model writes use transactions and clean up published files on failure.
- Secrets never enter URLs, logs, templates, Git, or test fixtures.
- Product definitions and raster/vector checks are reviewed as domain changes,
  separately from generic infrastructure refactors.

## Main contributor guides

- [Testing](testing.md)
- [Upload page components](upload-pages.md)
- [Database lifecycle and migrations](database-migrations.md)
- [Writing documentation](documentation.md)
- [Product onboarding](product-onboarding.md)
- [Product definitions and reporting](product-definitions.md)
- [Repository layout](../architecture/repository-layout.md)
- [Frontend vendor assets](frontend-vendor-assets.md)
