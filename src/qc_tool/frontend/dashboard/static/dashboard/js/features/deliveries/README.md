# Deliveries browser modules

The Deliveries page keeps server-backed table behavior separate from row
presentation and mutations:

| Module | Responsibility |
| --- | --- |
| `table.js` | Filters, pagination, server queries, sorting, result counts, and table accessibility |
| `formatters.js` | Safe scalar formatting and shared action eligibility |
| `rows/status.js` | Text-first delivery lifecycle presentation |
| `rows/actions.js` | State-aware action ordering and row controls |
| `rows/overview.js` | Composite delivery, product/AOI, status, and action markup |
| `actions.js` | Selection tray and delegated single/bulk mutation handling |
| `dialogs.js` | Confirmation and operation-result dialogs |
| `polling.js` | Bounded refresh while QC jobs are active |
| `index.js` | Declarative feature startup only |

The JSON endpoint remains presentation-neutral. A delivery row is rendered as
one overview rather than database-shaped Status or Actions columns. Keep the
filename as the job-history link, render lifecycle status as text as well as
color, put the most useful next action first, and keep Delete last in DOM and
visual order.

The matching styles use the same ownership under
`css/features/deliveries/rows/`: overview composition, status badges, and row
actions. Responsive rules stay in `responsive.css` so all row components
collapse at the same breakpoint.
