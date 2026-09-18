# Deliveries browser modules

The Deliveries page keeps server-backed table behavior separate from row
presentation and mutations:

| Module             | Responsibility                                                                            |
| ------------------ | ----------------------------------------------------------------------------------------- |
| `table.js`         | Filters, pagination, server queries, sorting, the column chooser, and table accessibility |
| `formatters.js`    | Safe scalar formatting and shared action eligibility                                      |
| `rows/status.js`   | Text-first delivery lifecycle presentation                                                |
| `rows/actions.js`  | State-aware action ordering and row controls                                              |
| `rows/overview.js` | Safe formatters for each semantic delivery table column                                   |
| `actions.js`       | Selection tray and delegated single/bulk mutation handling                                |
| `dialogs.js`       | Confirmation and operation-result dialogs                                                 |
| `polling.js`       | Bounded refresh while QC jobs are active                                                  |
| `index.js`         | Declarative feature startup only                                                          |

Delivery, Status, and Next action are always-visible workflow columns.
Product/product unit and Uploaded are shown initially; Size, Source, Owner, and ID
are available from the Columns control. The filename is the primary link to
the delivery's QC history, with file size as secondary metadata. Product names
use the authorized catalog URL supplied by the JSON endpoint, which resolves
the selected submission or QC run's product. Never build a product URL from a
QC recipe identifier: one recipe can serve several catalog products.

Use medium emphasis for filenames, normal text for product links and dates,
and muted metadata. Render lifecycle status as text as well as color, and only
show verified product unit after successful QC. Keep QC result/progress and history links
beside status; a failed delivery's result is its primary next action instead.
Promote one non-destructive workflow action, keep supporting actions quiet,
and keep Delete last. Running deliveries need no action button; their progress
is available with status. Submitted and accepted deliveries retain a quiet
link to their submission.

The matching styles use the same ownership under
`css/features/deliveries/rows/`: cell content, status badges, and row actions.
Responsive rules stay in `responsive.css`; narrow screens retain the semantic
columns inside a labelled, keyboard-focusable horizontal scroll region.

The toolbar and table shell come from the shared `QcDataTableUi` component,
the shared table-toolbar template, and `css/ui/data-table.css`. Initialize a
table once through `QcDataTableUi.create()`, supplying its page-specific
options, accessible labels, and export provider. The shared initializer keeps
column controls, sorting accessibility, and the Export menu consistent after
refreshes and column changes.

`QcTableExports` renders the same **JSON, CSV, XLSX, XML** menu for every
exportable table. Formats and order come from the central server registry;
Deliveries does not define its own list or generate files in browser code.
Its `server` export provider sends `exportQuery()` filters and ordering to the
delivery export endpoint. Pagination and column-selection parameters are
removed so the download includes all matching records and the complete public
export schema within the user's access scope. Hiding columns in the table does
not remove them from downloads. The endpoint validates its column allowlist
and uses the same serializers as other table exports. Keep selection and
action controls out of the export schema.

See the [table-page development guide](../../../../../../../../../docs/development/table-pages.md)
for filter composition, export providers, column metadata, and verification.
