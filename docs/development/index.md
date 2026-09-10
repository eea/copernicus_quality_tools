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

## Reusable table pages

Use `dashboard/shared/section_tabs.html` for navigation within a table card.
Each tab supplies `label`, `active`, and either a `url` for page navigation or a
`value` for an interactive table view. Counts are optional. Interactive views
also supply the include's `data_attribute` and `controls` arguments so their
controller can update the selected button and identify the controlled table.
Set a tab's `align_end` flag to align a secondary view at the end of the same
navigation row. Products and Deliveries use the same template and
`ui/section-tabs.css` styles.

Use `QcDataTableUi` and `ui/data-table.css` for Bootstrap Table controls, keyboard
sorting, responsive scrolling, and export buttons. Follow the
[table page guide](table-pages.md) for shared filter toolbars, initialization,
column metadata, and client/server export contracts. Keep domain-specific filters
and actions in the page controller. Define workflow membership and action-group priority on the
server, apply access scope before counting or filtering, and group and sort
before pagination. Deliveries uses `listing/workflows.py` as the shared source
for view membership, labels, descriptions and action groups. Workflow selection
(`delivery_view`) and optional status filtering (`delivery_status`) are separate;
view counts describe all matching stages before those two filters are applied. A server-backed export must use the same filters and ordering as
the visible table. Keep less common filters in an expandable section and retain
a selected filter even when its result count becomes zero.

## Main contributor guides

- [Testing](testing.md)
- [Upload page components](upload-pages.md)
- [Table page components](table-pages.md)
- [Database lifecycle and migrations](database-migrations.md)
- [Writing documentation](documentation.md)
- [Product onboarding](product-onboarding.md)
- [Product definitions and reporting](product-definitions.md)
- [Repository layout](../architecture/repository-layout.md)
- [Frontend vendor assets](frontend-vendor-assets.md)
