---
title: Table pages
parent: Development
nav_order: 7
---

# Table pages

Table pages share search and filter presentation, column selection, export
controls, keyboard sorting, and scroll regions. Page controllers own their
business filters, permissions, row formatters, and actions. Use these shared
components when adding or changing a table instead of copying another page's
toolbar and event handlers.

## Components and responsibilities

| Component | Responsibility |
| --- | --- |
| `dashboard/shared/tables/toolbar.html` | Search, optional sort, filter disclosure, clear button, and optional refresh button |
| `QcTableFilters` in `shared/table-filters.js` | Disclosure state, applied-filter count, clear-button visibility, and focus management |
| `QcDataTableUi` in `shared/data-table-ui.js` | Bootstrap Table initialization, common options, export menu, and generated-control accessibility |
| `QcTableExports` in `shared/table-exports.js` | One export menu, complete data-column projection, and requests to the appropriate export provider |
| `ui/table-toolbar.css` and `ui/data-table.css` | Responsive toolbar, column menus, table layout, and horizontal scrolling |
| `dashboard/services/exports/` | The shared JSON, CSV, XLSX, and XML format registry and serializers |

Template paths are relative to `dashboard/templates/`. JavaScript and CSS paths
are relative to `dashboard/static/dashboard/`. Extend
`dashboard/layouts/workspace_page.html` and retain `block.super` in stylesheet
and script blocks to load the shared components. Load the Bootstrap Table
stylesheet on pages that use the plugin.

## Initialize one table

Use a semantic table with a caption, named columns, and a stable ID. Wrap it in
`qc-data-table-region`, and add `qc-data-table` to its classes. Initialize it
once from the page controller:

```javascript
var $table = QcDataTableUi.create("#tbl-example", {
    options: {
        pagination: true,
        sidePagination: "client",
        search: true,
        toolbar: "#example-toolbar",
        searchSelector: "#example-search",
        sortName: "name",
        sortOrder: "asc"
    },
    labels: {
        subject: "examples",
        region: "Examples table",
        search: "Search examples"
    },
    exports: {filename: "examples"}
});
```

`create(table, {options, labels, exports})` returns the jQuery table. `options`
contains Bootstrap Table options; `labels` supplies accessible names. Omit
`exports` when the table has no suitable export. Every export menu provides
**JSON, CSV, XLSX, XML**, in that order. Common column controls and keyboard
sorting are added by the shared
initializer and maintained after table refreshes and column changes.

The initializer marks enclosing workspace cards with `qc-data-table-card` so
toolbar menus can extend beyond the card. Keep overflow clipping off toolbar
ancestors; horizontal scrolling belongs to the table body, below its controls.

Refresh and Export use compact icon buttons with accessible names and hover
labels. Columns keeps its label beside a table icon to make display settings
recognizable. The shared initializer updates the plugin's existing buttons
without replacing their event handlers. Use the shared SVG sprite and toolbar
styles; page controllers should not add their own icons or visible button text.

Do not put `data-toggle="table"` on a table initialized by a controller. The
vendored plugin automatically initializes those elements at document-ready;
mixing the two paths can ignore page options or initialize a table twice.
Use native Bootstrap Table methods for later changes, such as `refresh`,
`filterBy`, or `refreshOptions`.

Keep simple contextual tables simple. A form's checkbox grid does not need
column menus or export. QC result pages use the shared menu for their check
results table; dedicated PDF/JSON reports and job logs remain separate artifact
downloads.

## Show record context above a table

Use `dashboard/shared/entity_summary.html` for a record's identity and a few
useful facts, such as the delivery whose QC history is being viewed. Load
`dashboard/css/ui/entity-summary.css` alongside the shared workspace styles.

```django
{% include "dashboard/shared/entity_summary.html" with id="delivery-summary" summary=delivery_summary only %}
```

The summary has a `title`, a short `kind`, an optional `reference` and SVG
`icon`, an optional `description` with `description_label` and authorized
`description_url`, and a `facts` list. Each fact has a `label` and either a
plain `value` or a `datetime`. Datetimes include the displayed timezone and a
machine-readable `<time>` value. Supply a unique `id` for the heading.

The optional `status` contains `value`, `label`, and `tone` (`neutral`, `primary`,
`success`, `warning`, or `danger`), with `status_label` naming the field. An
optional `action` contains `url`, `label`, and an SVG `icon`. Supply actions only
when the server's authorization and lifecycle checks allow them.

Show the filename or record name once. Use the description for its parent
product or other context, and omit unavailable optional facts. When a summary
shows changing state, load `shared/entity-summary.js` and call
`QcEntitySummary.updateState(element, summary)` with fresh server data. It updates
the status and permitted action without replacing the summary's identity or
moving keyboard focus on an unchanged action.

Job history requests `include_delivery=1` from its existing data endpoint to
receive `{rows, delivery_summary}`. Refreshing the table also refreshes delivery
status and first-run availability; filtering loaded rows never decides whether
a delivery has previous runs. Requests without that flag keep the plain job
array response.

Resolve product links through the shared delivery product-link service, using
the viewer's access scope and the selected catalog product.

## Compose the filter toolbar

Include the shared toolbar with page-specific field partials:

```django
{% include "dashboard/shared/tables/toolbar.html" with id="example-toolbar" table_id="tbl-example" search_id="example-search" search_label="Search examples" search_placeholder="Name or identifier" filters_template="dashboard/examples/table_filters.html" clear_id="example-clear" toggle_id="example-filter-toggle" panel_id="example-filter-panel" summary_id="example-filter-summary" %}
```

`id`, `table_id`, and the search ID and label identify the toolbar and its table.
Each ID must be unique on the page. Additional options are:

| Argument | Use |
| --- | --- |
| `filters_template` | A partial containing labelled filter fields; the caller's context remains available |
| `sort_template` | An optional labelled sort select |
| `clear_id` | Clear-filter button ID |
| `toggle_id`, `panel_id`, `summary_id` | Required together when providing filter fields |
| `refresh_id`, `refresh_label` | Optional refresh button and its accessible name |
| `hidden` | Hide the toolbar until its page controller is ready |

Use `qc-table-toolbar__field` around each filter and `form-control` on inputs.
Preserve the shared `data-table-filter-*` hooks. Bind the toolbar through
Bootstrap Table's `toolbar: "#example-toolbar"` option. The plugin places it
inside `.bs-bars`; shared CSS combines it with the generated Columns and Export
controls on the same white surface. Keep those generated controls in their
native `.fixed-table-toolbar` parent: the plugin uses that parent to find and
update column controls.

The disclosure component handles presentation; the page controller applies
filter values to its own query:

```javascript
var filters = QcTableFilters.create(
    document.getElementById("example-toolbar"),
    {onClear: clearPageFilters}
);

filters.update({active: Boolean(search || selectedProduct), count: selectedProduct ? 1 : 0});
filters.setExpanded(Boolean(selectedProduct));
```

`active` controls the clear button and should include search. `count` describes
the applied filters inside the disclosure; it does not count the search or sort
order. Call `update` whenever the page state changes, including URL restoration
and filter clearing. `setExpanded` opens or closes the panel. `destroy` removes
the component's listeners when removing the toolbar from the document.

The component closes the disclosure on Escape and returns focus safely when a
focused panel or clear button disappears. Page code remains responsible for
debounced requests, resetting pagination, and cancelling pending search work
when filters are cleared. Keep a selected filter available even if its result
count becomes zero.

## Define column and export semantics

Column metadata belongs beside the table header or in its column options:

```html
<th data-field="name">Name</th>
<th data-field="rendered_status" data-export-field="status">Status</th>
<th data-field="actions" data-switchable="false" data-exportable="false">Actions</th>
```

- Make every data column available in Columns, including identity, status, and
  columns hidden by default with `data-visible="false"`. Keep identity columns
  visible initially, and reserve `data-switchable="false"` for fixed action or
  selection controls.
- The shared chooser keeps at least one data column visible. Its All columns
  option includes columns hidden by default.
- Mark actions with `data-exportable="false"`. Selection checkboxes, radio
  controls, and action fields are excluded from export.
- Use `data-export-field` when the displayed column represents a different raw
  field in browser-provided exports.
- Exports include all declared exportable data columns, including columns hidden
  by default or through the Columns menu. The column chooser changes the page
  presentation only; it does not change the downloaded file.
- Browser-provided exports use the table's declared column order. Server
  providers use their complete public export schema, including fields that do
  not have a displayed table column. Keep permission checks in the data provider;
  hiding a column is never an authorization mechanism.

Browser-provided exports read row data rather than rendered formatters. Plain strings
remain plain, so a filename containing `<` or `>` is preserved. For a table
whose row data contains HTML, explicitly list `htmlFields` in its export
settings or use `data-export-html="true"` on the relevant headers. HTML text
is extracted through an inert template.

For a domain-specific value, configure `exports.values` using the displayed
column field as the key:

```javascript
exports: {
    filename: "examples",
    htmlFields: ["description"],
    values: {
        coverage: function (value, row, column) {
            return row.accepted_count;
        }
    }
}
```

A column can alternatively provide an `exportValue(value, row, column)`
callback in JavaScript. The settings callback takes precedence. Preserve
numeric values as numbers; choose values that explain the column to someone
reading the file without access to the page.

## Choose an export provider

| Table data | Export provider | Formats |
| --- | --- | --- |
| All authorized rows loaded in the browser, filtered/paginated locally | Shared table conversion endpoint; receives projected rows from the browser | JSON, CSV, XLSX, XML |
| Server-side filtering or pagination | Authorized server endpoint; queries all matching rows | JSON, CSV, XLSX, XML |

The menu and file conversion are shared regardless of where rows are loaded.
`EXPORT_FORMAT_OPTIONS` in `dashboard/services/exports/tabular.py` owns the
format names, labels, and order exposed to the browser. Do not define a
page-specific format list or write another export dropdown. Keep the menu
markup and feedback in `QcTableExports`, and styling in the shared table CSS.

For fully loaded tables, the browser projects all locally matching rows and
all declared exportable data columns, then sends that data to the authenticated, CSRF-protected
table conversion endpoint. The endpoint converts only the supplied data; it
does not query application records or treat browser fields as permission to
retrieve them. The same server serializers produce every format, including
XLSX, so pages do not need a browser spreadsheet library.

`workspace_page.html` supplies the `qc-table-export-config` JSON script with
the endpoint URL and central format options. New workspace pages inherit it;
do not hard-code that configuration in a page controller. The conversion
request is a JSON POST to `/data/tables/export/` (route name `table_export`):

```json
{
  "format": "xlsx",
  "filename": "examples",
  "columns": [{"field": "name", "label": "Name"}],
  "rows": [{"name": "Example product"}]
}
```

The request is bounded to 8 MiB, 256 columns, 50,000 rows, and 500,000 cells.
Oversized bodies receive HTTP 413; invalid structures or row/column/cell limits
receive HTTP 400. Text and serialized metadata cells are limited to 32,767
characters so XLSX cannot silently shorten their content. Nested metadata has
a maximum depth of 32. No rows are silently truncated. For larger datasets, supply
an access-scoped query export provider rather than raising browser payload
limits or fetching all data just to export it.

This provider includes all locally matching rows, not just the displayed page.
Do not use it for server-paginated tables: the browser does not have the full
result. The shared exporter rejects a table configured with
`sidePagination: "server"` unless a server provider is supplied. Native HTML
tables with server pagination require the same care; changing their Bootstrap
Table settings cannot make unloaded rows available.

Configure a server provider with the same filters and ordering used for rows:

```javascript
exports: {
    filename: "deliveries",
    server: {url: config.exportUrl, getQuery: exportQuery}
}
```

The shared exporter sends `format`, filters, and ordering. It removes pagination
parameters and any `columns` parameter so the endpoint always uses its complete
public export schema. Server exports must query all matching rows with no
listing-page cap; reuse the same access scope, workflow membership, filters,
and sort rules as the table. Deliveries applies its scope before export and
uses the same four serializers as browser-provided tables.

The endpoint independently validates format and column allowlists. It must
enforce authentication, permissions, and object access even when called without
the page. Keep secret or inaccessible fields out of its allowed column
specification. Direct API callers may request an explicit column subset where
the endpoint supports it; the shared table UI always requests all columns.
Reject unsupported formats and malformed column requests rather than silently
producing a different file.

The file formats represent the same complete column set and matching rows:

- JSON contains an array of records keyed by export field; nulls, booleans,
  numbers, and nested metadata retain their data types.
- CSV contains labelled headers and spreadsheet-safe string cells. Its UTF-8
  byte-order mark lets desktop Excel recognize Unicode.
- XLSX contains labelled headers and preserves numeric and boolean values.
  Untrusted strings are protected against formula interpretation. Results that
  exceed Excel's worksheet row limit continue on sheets with repeated headers.
- XML contains a `table` root, a `columns` header, and `rows`. Each `cell`
  identifies its `field` and value `type`; nested metadata uses type `json`.
  Field names are attributes, so names containing spaces or punctuation do not
  become invalid element names.

Datetime values use ISO 8601 text to retain timezone information. XML escaping
belongs to the serializer; XML-incompatible control characters are removed
from XML and spreadsheet text. Reuse these serializers rather than building
CSV or XML by concatenation or writing untrusted values directly into
spreadsheets.

## Extend and verify

1. Choose a plain table or a rich table based on actual user needs.
2. Reuse the toolbar and initializer, supplying page labels and domain fields.
3. Decide whether every authorized row is loaded locally before selecting an
   export provider. Reuse all four shared formats for either provider.
4. Test filtering and clearing, empty results, pagination, column changes, and
   export after both filtering and column changes. Hidden data columns must
   remain in every format, while action and selection controls remain excluded.
5. For server exports, verify full-result export, matching ordering, access
   restrictions, format/column validation, and spreadsheet formula handling.
6. Check keyboard focus, responsive controls, and dropdown visibility. Keep
   horizontal scrolling on the table body so toolbar menus remain usable.

Behavior tests live in `dashboard/tests/javascript/table_exports.test.cjs` and
`table_filters.test.cjs`; page adapters have their own tests.
`dashboard/tests/test_delivery_exports.py` covers server export behavior, and
`dashboard/services/tests/test_spreadsheet_exports.py` covers serialization.
Use the [testing guide](testing.md) to run focused suites.
