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

The JSON endpoint remains presentation-neutral. Delivery, job status, and
Actions are always-visible workflow columns. Product/AOI and Uploaded are
shown initially; Size, Source, Owner, and ID are available from Bootstrap
Table's Columns control. Keep the filename as plain text with a separate icon
and `Job history` link beneath it. Render lifecycle status as text as well as
color, highlight submitted rows with a light success background, and only show
the verified AOI after the latest QC job succeeds. Put the most useful next
action first, and keep Delete last in DOM and visual order. In Actions, promote
exactly one non-destructive lifecycle action as the primary button. Keep the
remaining actions visible as quiet icon-and-text controls, with Delete using
restrained danger styling instead of competing with the primary task.

The matching styles use the same ownership under
`css/features/deliveries/rows/`: cell content, status badges, and row actions.
Responsive rules stay in `responsive.css`; narrow screens retain the semantic
columns inside a labelled, keyboard-focusable horizontal scroll region.

The toolbar and table shell come from the shared `QcDataTableUi` component and
`css/ui/data-table.css`. A Bootstrap Table opts in with a
`qc-data-table-region` wrapper, passes its page-specific behavior through
`QcDataTableUi.options()`, and calls `QcDataTableUi.enhance()` after
initialization. Deliveries supplies a custom server-export button so exported
rows continue to respect account access, active filters, and sorting.
