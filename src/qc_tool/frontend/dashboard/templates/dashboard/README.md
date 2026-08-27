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

## Breadcrumb hierarchy

Top-level pages do not render breadcrumbs because the H1 already identifies
their location. Use `shared/breadcrumbs.html` on child pages only. The current
item is always plain text and the ancestors are canonical links:

```django
{% url "products" as products_url %}
{% include "dashboard/shared/breadcrumbs.html" with parent_label="Products" parent_url=products_url current_label=product.name %}
```

For a third ancestor, pass `section_label` and `section_url` before the parent.
Breadcrumbs start at the owning area; they never add Dashboard as a synthetic
root. Dashboard and every other level-one page render no breadcrumb.
Compatibility URLs must never appear in breadcrumbs.

## Shared visual primitives

Cross-feature primitives live in `static/dashboard/css/ui/`:

- `tokens.css`: semantic colors, widths, radii, focus ring, and elevation
- `workspace-content.css`: page, breadcrumb, card, callout, and responsive page composition
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
