# Browser page composition

QC Tool pages use three layouts, each with a deliberately narrow purpose:

| Layout | Use it for |
| --- | --- |
| `layouts/base.html` | Public, account, error, and other pages that must not require the authenticated workspace navigation |
| `layouts/workspace.html` | Unusual authenticated screens that need the workspace sidebar but cannot use the standard page composition |
| `layouts/workspace_page.html` | Normal authenticated pages; this is the default for new workspace features |

`workspace_page.html` owns the page width, breadcrumb position, one primary
heading, subtitle, header actions, content, and page-level modals. A feature
template supplies content through these blocks:

- `title` and `main_class`
- `workspace_css` (start with `{{ block.super }}`)
- `page_breadcrumbs`
- `page_title`, `page_subtitle`, and optional `page_header_meta`
- `page_actions`
- `page_content` and optional `page_modals`

Do not reproduce the page container or header inside a feature template.

## Application header

`shared/header.html` owns the header frame for workspace, public API, account,
error, and Admin pages. Both application layouts include it with an explicit
context (`only`); feature views must not change header behavior through unrelated
context variables. New pages inherit their area's layout rather than recreating
header markup.

| Component | Responsibility |
| --- | --- |
| `shared/header.html` | Maintenance notice, linked brand, optional return control, responsive menu, and optional secondary navigation |
| `shared/brand.html` | Original Copernicus/CLMS logos, application title, and optional area label |
| `shared/profile_menu.html` | Native Profile disclosure, optional identity/settings link, and logout action |
| `shared/logout_form.html` | CSRF-protected POST with maintenance write protection |
| `shared/navigation.html` | Permission-aware workspace/public navigation and account destinations |
| `admin/includes/header_account_menu.html` and `header_navigation.html` | Admin account destinations and permitted administration tasks |

The containing layout supplies the brand URL, navigation template, and visibility.
Workspace and API brands link to `dashboard_home`; Admin brands link to
`admin:index`. API and Admin use the same **Back to workspace** arrow and area
label (`CLMS QC Tool | API` or `CLMS QC Tool | Admin`). The return control uses
the canonical Dashboard URL, so it works after direct entry as well as navigation
from the workspace. Admin keeps one workspace-return control; its other
navigation and authentication/recovery destinations remain inside Admin.
Admin sign-in hides account and task navigation.
Admin always uses the shared light palette. Its base template omits Django's
theme script and dark stylesheet, so saved theme choices and system appearance
do not change the page. Profile, logout, back, and mobile controls keep using
the shared components and styles used by the normal workspace and API.

Standalone areas configure the shared pattern through the base layout, without
copying header markup or adding feature-specific styles:

```django
{% block header %}
{% url 'dashboard_home' as workspace_url %}
{% with header_brand_context="API" header_return_url=workspace_url %}{{ block.super }}{% endwith %}
{% endblock header %}
```

Account and error pages with a different safe return destination override the
layout's `header` block, set `header_brand_url`, and render `block.super`:

```django
{% block header %}
{% with header_brand_url=account_return_url %}{{ block.super }}{% endwith %}
{% endblock header %}
```

Do not put overridable blocks inside an included component: Django includes do
not participate in the caller's template inheritance.

`ui/header.css` owns header geometry and responsive navigation, `ui/brand.css`
owns identity presentation, and `ui/navigation.css` owns menu appearance. Admin
maps shared color variables to its light palette in `admin/shell.css`; feature styles
must not redefine the header. `shared/navigation.js` progressively enhances the
mobile toggle and adds Escape/outside-click dismissal. Without JavaScript,
navigation remains visible and Profile works through native `details`/`summary`.
The header does not require Bootstrap JavaScript.

All navigation supplied to the header, including Admin task links, belongs
inside `#primary-navigation-menu`. The shared hamburger controls that entire
region on small screens. The desktop layout places account links beside the
brand and optional area links on the next row using the same component; do not
put a second mobile menu or navigation outside the controlled region.

## Breadcrumb hierarchy

`shared/breadcrumbs.html` is the breadcrumb component for every layout,
including public sign-in and account pages. Its `qc-breadcrumb` styles live in
`ui/breadcrumbs.css`, loaded once by `base.html`; using it does not require the
workspace sidebar or workspace content stylesheet. Do not add Bootstrap
`breadcrumb` markup or feature-specific breadcrumb styles.

Top-level workspace pages do not render breadcrumbs because the H1 already
identifies their location. The current item is always plain text with
`aria-current="page"`; navigable ancestors use canonical links:

```django
{% url "products" as products_url %}
{% include "dashboard/shared/breadcrumbs.html" with parent_label="Products" parent_url=products_url current_label=product.name only %}
```

For a three-level trail, pass `section_label` and `section_url` before the
parent. For deeper or data-driven hierarchies, supply `ancestors`, an ordered
list of dictionaries with `label` and optional `url`, plus `current_label`:

```python
breadcrumb_ancestors = [
    {"label": "Deliveries", "url": reverse("deliveries")},
    {"label": "QC job history", "url": history_url},
    {"label": "QC job result", "url": result_url},
]
```

```django
{% include "dashboard/shared/breadcrumbs.html" with ancestors=breadcrumb_ancestors current_label="Report" only %}
```

A nonempty `ancestors` list takes precedence over the shorthand section/parent
arguments. An ancestor without a URL renders as a plain section label, never
an empty link. The component renders nothing without a current label or any
ancestors. It supports a custom `aria_label` (default: `Breadcrumb`), wraps long
labels on small screens, and hides separators from assistive technology.
Always use `only` so unrelated page context cannot change the trail.

Workspace breadcrumbs start at the owning area; they never add Dashboard as a
synthetic root. Dashboard and every other level-one workspace page render no
breadcrumb. Public and account pages choose their own meaningful root and
preserve permission-aware return links. Compatibility URLs must never appear
in breadcrumbs.

## Shared visual primitives

Cross-feature primitives live in `static/dashboard/css/ui/`:

- `tokens.css`: semantic colors, widths, radii, focus ring, and elevation
- `breadcrumbs.css`: navigation trails shared across all layouts
- `workspace-content.css`: page, card, callout, and responsive workspace composition
- `actions.css`: primary, secondary, success, danger, danger-outline, quiet,
  icon, and compact button variants

The shared `--qc-workspace-background` token owns the application page canvas,
including the public API reference. Feature styles must not set a background
on their page root; they may style only the content inside that canvas.

Feature layout and data presentation stay in
`static/dashboard/css/features/<feature>/`. A shared UI stylesheet must not
contain selectors for a product, delivery, boundary, job, or API-specific
component.

Use semantic button colors consistently: blue for the primary page action,
green for starting QC or another successful action, red for destructive
actions, and a white/blue secondary button for navigation or downloads. Keep
the Bootstrap `btn` class while the application still loads Bootstrap, and add
the appropriate `btn-qc-*` class for the QC Tool contract.

Native Django Admin model controls use those same `btn-qc-*` classes through
the adapters in `frontend/templates/admin/`: submit rows, bulk actions, search,
object tools, and deletion confirmations. Single and bulk deletion share
`admin/includes/delete_confirmation_form.html`, including CSRF and explicit
confirmation fields. Keep permissions, filters, and form semantics in these
adapters and visual rules in `ui/actions.css`; review the adapters against the
installed Django templates when upgrading Django. Admin layout styles may
arrange and wrap actions, but must not recreate their button appearance.
Upstream authentication forms keep their original markup and behavior; narrowly
scoped native submit selectors join the same shared action rules, including the
destructive variant for disabling password authentication.

JavaScript behavior uses stable IDs, `data-*` configuration, and feature-local
classes. Styling must not be the only JavaScript hook. New scripts belong under
`static/dashboard/js/features/<feature>/`; keep executable page logic out of
templates except for small, escaped configuration values.

## Adding a browser page

1. Put the canonical route in the owning feature URL module and classify its permission.
2. Extend `workspace_page.html` unless the page is intentionally public or lacks workspace navigation.
3. Add the canonical breadcrumb hierarchy, exactly one H1, a useful subtitle, and permission-scoped actions.
4. Reuse cards, notices, and QC button classes before adding a feature component.
5. Put feature CSS and JavaScript in matching nested feature directories.
6. Add semantic presentation coverage to `tests/test_page_chrome.py` plus focused tests for the feature content.
