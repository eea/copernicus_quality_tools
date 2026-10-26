---
title: UI component ownership
parent: Development
nav_order: 10
---

# UI component ownership

Build each page from the smallest existing component that owns the behavior.
When two features repeat the same behavior or markup, move it to their nearest
shared owner and migrate both callers. Keep permissions, validation, actions and
user feedback in the feature that makes those decisions.

## Where shared code belongs

Paths below are relative to `src/qc_tool/frontend/`.

| Responsibility | Owner |
| --- | --- |
| Workspace/public page frames, header, breadcrumbs, notices and back links | `dashboard/templates/dashboard/layouts/` and `dashboard/templates/dashboard/shared/` |
| Design tokens, buttons, cards, table controls, tabs and upload presentation | `dashboard/static/dashboard/css/ui/` |
| Browser mechanics used across features | `dashboard/static/dashboard/js/shared/` |
| Accounts form fields and non-field errors | `accounts/templates/accounts/includes/` |
| Bulk product selection widget and its assets | `accounts/templates/accounts/widgets/`, `accounts/static/accounts/{js,css}/admin/` |
| Admin shell and feature frames | `templates/admin/base_site.html`, `dashboard/templates/admin/*_base.html` |
| Admin-only reusable fragments | `dashboard/templates/admin/includes/`, with transfer fragments under `transfers/` |
| Announcement read state and unavailable-state handling | `dashboard/services/configuration/presentation.py` |
| Announcement rendering and notice styles shared with maintenance | `dashboard/templates/dashboard/shared/announcements/`, `dashboard/static/dashboard/css/ui/notice.css` |
| Domain rules and queries | The owning `accounts/services/` or `dashboard/services/<feature>/` package |

Do not create a root `utils` collection or move feature-specific rules into a
shared UI module. A shared component should describe one responsibility and have
actual callers. Split large modules at responsibility boundaries rather than
at an arbitrary line count.

Template includes use explicit arguments and `only` when they need no enclosing
request context. Frame templates inherit the owning layout. Form fragments do
not introduce forms, CSRF tokens or submit actions; their callers own those.
Load browser dependencies before their consumers, only on pages that use them.
Reuse `btn-qc-*` variants from `ui/actions.css`; feature CSS owns layout and
purpose-specific sizing, rather than another copy of button colors and states.

See the [page composition contract](../../src/qc_tool/frontend/dashboard/templates/dashboard/README.md),
[upload guide](upload-pages.md) and [table guide](table-pages.md) for APIs and examples.

## Page-by-page reuse map

Use this inventory when changing UI and when reviewing cross-page reuse.
Inspect each listed page group, including its empty/error state and narrow
layout, before introducing a new component with an existing responsibility.

| Page group | Composition and behavior to reuse |
| --- | --- |
| Dashboard overview | Workspace page frame, shared announcement notice, cards and actions |
| Deliveries: listing, upload, review | Table filters/controls/exports, upload frame/picker/queue, back link and shared buttons; delivery transport and review decisions stay local |
| Products: listing, detail, upload, removal | Section tabs, table controls, upload adapters and back link; product identity, approval and deletion rules stay local |
| QC jobs: setup, history, result | Entity summaries, announcement notice, back link, table/button primitives; check/result semantics and history formatters stay local |
| Submissions: queue and detail | Shared table/feedback/button primitives and checkbox state; eligibility, bulk requests and review decisions stay local |
| API reference | Shared public header, buttons and clipboard mechanics; operation filtering, expansion and request examples stay local |
| Account settings, credentials, sign-in, password forms | Shared header, fields/errors, buttons and clipboard mechanics; credential lifecycle, confirmation and authentication destinations stay local |
| Forbidden/not found pages | Shared error frame, Home action and button styles; permission-aware destinations stay local |
| Admin overview and user management | Admin shell, direction cards, account navigation and bulk product widget; grants and role validation stay in Accounts |
| Admin boundaries: catalog, upload, retained packages | Admin boundary frame, shared table/export/upload components; archive validation and retention stay local |
| Admin Notifications | Shared Admin cards, announcement read state and existing preview; publishing remains an Admin action |
| Admin Database: overview, tables, records and record detail | `database_base.html`, breadcrumbs, page header/actions and section tabs; account records retain their User management context |
| Admin Storage: browse, file, connection, library and trash | `storage_base.html`, return-context fields, shared tabs, clipboard and checkbox mechanics; file actions, authorization and status messages stay local |
| Admin Maintenance and separate export/import pages | Admin panels/buttons, existing transfer frame, pending-status fragment and operation/history components; maintenance, staging and background operation rules stay local |

Similar-looking polling is not necessarily the same contract. Transfer GET
polling, maintenance generation checks and delivery refresh have different
timeouts, stale-response handling and recovery behavior. Share their established
transport primitives without merging these workflow state machines.

## Iterative review

1. Map the route to its view, service, template, CSS and controller using the
   [frontend feature map](../../src/qc_tool/frontend/dashboard/README.md).
2. Search for the behavior, class and fragment across the other page groups.
   Compare permission checks, accessibility hooks, loading order and fallback
   behavior before deciding that implementations are equivalent.
3. Extract the common responsibility, migrate every matching caller, then
   remove obsolete helpers and styles. Keep meaningful differences explicit at
   the caller. Preserve uploaded specification bytes.
4. Verify behavior at the affected boundary: template rendering/permissions,
   browser-event tests for shared mechanics, and desktop/mobile review for
   layout changes. Run the [frontend regression suite](testing.md#frontend-regression-suite)
   after combining batches.
5. Recheck the inventory and update the owning contract when its API changes.
   Measure source reduction including new shared files; deleting lines is useful
   only when the resulting ownership and behavior are clearer.
