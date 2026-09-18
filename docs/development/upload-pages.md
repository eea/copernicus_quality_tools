---
title: Upload pages
parent: Development
nav_order: 6
---

# Upload pages

Upload pages share file selection, file rows, progress and feedback. Products and
deliveries also share an explicit review queue: selecting a file stages it.
Products use **Add** and **Add all**. Deliveries use **Upload** for new files and
**Replace and upload** for eligible existing deliveries. Batch actions process
the reviewed files sequentially.
Boundary packages retain their explicit **Upload and activate** operation.

## Components and responsibilities

| Source | Responsibility |
| --- | --- |
| [Upload layout][layout] | Workspace shell, shared assets and accessible announcements |
| [Queue layout][queue-layout] | Loads the queue controller after the shared upload helpers |
| [Picker template][picker] | Native file input, chooser, format guidance and field errors |
| [Queue template][queue-template] | File list, ready/completed counts, batch action and pending guidance |
| [Shared presentation][helpers] | Picker validation, drag-and-drop, file rows, notices and size formatting |
| [Queue controller][queue] | Staging, individual/batch actions, sequential processing and partial results |
| [Shared styles][styles] | Responsive picker, file rows, state colors, progress and actions |
| [Product adapter][products] | One JSON specification per multipart request; admin-only server validation and versioning |
| [Delivery adapter][deliveries] | Own-user filename checks and a resumable transport for each requested file |
| [Boundary adapter][boundaries] | One ZIP request and confirmation of boundary activation |

Shared components do not contain feature endpoints, permissions or publication
rules. Adapters translate server responses into presentation states. Client
validation gives early feedback; the server independently enforces permissions,
CSRF, safe filenames, content limits, archive safety and domain rules.

## Add another queue-based page

1. Extend the queue layout. Fill the inherited `upload_id`, `upload_title`,
   `upload_description`, `upload_attributes` and `upload_body` blocks. Keep
   `block.super` when extending the script block.
2. Give the body `workspace-card__body qc-upload-body` classes. Include the
   picker and queue templates. The picker requires unique `id` and `input_id`
   values, labels and format guidance. It accepts a Django bound field as
   `input`, or generates one from `input_name`, `accept` and `multiple`.
3. Initialize `qcUpload.createQueue(root, options)` from the adapter. The root
   must contain one picker, queue and announcement region. Choosing files
   never invokes the transport; each selected file receives an explicit action.
4. Supply the adapter contract below. Treat each request independently. A
   failure must not erase or roll back other successful files in the batch.
5. Run all JavaScript suites and the affected Django presentation, permission
   and service tests described in [Testing](testing.md).

| Queue option | Contract |
| --- | --- |
| `extensions`, `maxBytes` | Allowed lowercase extensions without dots and optional per-file size limit |
| `key(file)` | Optional identity used to detect duplicate selections; defaults to the filename |
| `describe(file)` | Optional text displayed below the filename |
| `labels` | Optional action and state wording; defaults suit product additions, while delivery uploads supply their own labels |
| `check(entry)` | Optional asynchronous preflight; returns a blocked result or permits addition |
| `send(entry, report)` | Returns a promise which resolves only after server confirmation |

An entry retains its `file`, `key`, `state`, `attempted` flag and adapter-owned
`meta` across retries. A blocked preflight returns `{blocked: true, message,
url, linkLabel}`. Include an opaque `overwriteKey` to offer an explicit
overwrite action; the queue pins this key in `entry.overwriteKey` only when
the user selects the replacement action or the clearly labeled batch action. A changed key
at the next check requires another explicit choice. A successful send returns `{label, message, url, linkLabel}`.
`report({state, label, percent})` updates measurable transfer or pending
processing. An adapter may report `controls` with `pause`, `resume` and `cancel`
callbacks when its transport supports them.

Reject with an `Error` carrying a useful message. Set `redirecting` after shared
authentication handling redirects the browser; remaining batch requests stop.
`blocked` denotes a conflict requiring a different file, and `canceled` denotes
an interrupted upload. Set `recheck` on a stale-target conflict to clear the
overwrite choice and run preflight again on Retry. Retry otherwise uses the
same entry. The queue API exposes `picker`, `entries`, `add(entry)`,
`overwrite(entry)`, `addAll()` and `remove(entry)`.

The `labels` object supports `add`, `overwrite`, `addAll` and `overwriteAll` for
actions; `ready`, `pending`, `failed` and `running` for state wording; and
`completed` for the completed-file count. Keep these labels specific to the
adapter: product specifications are added, while delivery files are uploaded.

Ready rows show their primary action and Remove; eligible stored duplicates show
the replacement action and Remove; invalid or protected rows show an explanation
and Remove; failed rows expose Retry. The batch action is offered for at least
two ready or replaceable files after selection checks finish. Deliveries use
**Upload all (N)**, or **Replace and upload all (N)** when replacements are
present, with separate new/replacement counts. The batch action remains visible
but disabled while its files upload. It excludes blocked and failed files;
retries remain an explicit per-file decision. Completed rows retain their result
and a link to the created or existing record. Additional selections do not erase
previous outcomes.

## Product specification requests

The enhanced page accepts multiple JSON files, up to 1 MiB each. Each queued
request posts exactly one `definition_file` to `/products/upload/` with
`Accept: application/json` and the session CSRF token. The server returns
`status`, `created`, `product_ident`, `url` and `message` on success. An identical
existing specification returns `created: false` and is shown as **Already added**.
Invalid files receive an error while earlier successful additions remain intact.

Without JavaScript, the native multipart form supports one specification at a
time. Its fallback Add specification button carries `data-upload-native`; queue
enhancement hides it and uses per-file actions. The server always rejects
multiple files in a single request, regardless of browser input attributes.

## Delivery duplicate checks and retries

`POST /deliveries/upload/check/` accepts JSON `{filenames: [...]}` with between
1 and 100 plain ZIP filenames and a maximum request size of 64 KiB. Each result
includes `filename`, `exists`, `delivery_id`, `date_uploaded`, `url`,
`can_overwrite` and `overwrite_reason`. The
lookup uses only the signed-in user's non-deleted deliveries, including when
that user is an administrator. Other users' filenames and record metadata are
never disclosed. Responses are private and not cached.

Checks run when files are selected and immediately before the first **Upload** or
**Replace and upload**. Only the owner's local deliveries without submission records,
submission timestamps or waiting/running QC may be overwritten. S3 deliveries
and ambiguous duplicate database records are protected. The row explains the
reason and links to the existing delivery. Repeating a filename within the
current selection is a separate queue error, not an overwrite candidate.

An overwrite sends `overwrite_delivery_id` on every chunk request. The server
validates its owner, filename, current identity and eligibility again at
finalization. The parameter participates in the staging identity. If another
upload changes the target after the warning, the client requires a new explicit
choice; a batch never silently adopts a newer target.

Rejected submissions have a dedicated **Upload correction** action. Its page
uses the same queue and transfer adapter, restricted to one ZIP with the exact
original filename. `correction_submission_id` accompanies both the filename
preflight and every chunk request, along with `overwrite_delivery_id` for the
original delivery. The server verifies ownership, publication and rejection
state, active delivery identity and filename before accepting a correction.
The original submission remains immutable. A successful correction links
directly to QC setup for its fresh delivery; submission for review is a later
explicit action after the new checks pass.

The replacement is fully staged before the original is changed. Under the
shared filename lock, a durable transaction retires the original delivery and
allocates a hidden successor. A private journal records both identities and
inodes. The archive is replaced atomically, then the successor is activated in
a second transaction. This order ensures old QC cannot authorize replacement
bytes after a process interruption. The replacement starts without QC results
or submitted product unit state. The old QC history and original ZIP are retained; the
ZIP is a private `.previous` hard link in the upload's staging directory.

Ordinary caught failures restore the original when the successor has not
committed and storage/database access permits recovery. If the process or
recovery itself fails, the filename stays reserved and its journal allows the
same upload to finish. An already committed successor is never rolled back just
because confirmation failed. API local registration takes the same filename
lock and refuses existing or reserved filenames with HTTP 409. External tools
must not write over registered files directly in incoming storage.

Each selected delivery receives a random upload identifier when first sent.
Retries keep that identifier and overwrite target, allowing the server to resume staged chunks or
confirm its own previously committed registration. They do not repeat the
preflight because their own partially confirmed record could already exist.
A newly selected file receives a different identifier, even if its name and size
match an earlier upload, preventing accidental reuse of an old receipt.

Each active attempt owns a separate Resumable instance. Only explicitly queued
files reach that instance. Pause, resume and cancellation affect that file;
late callbacks cannot turn an errored or canceled attempt into success.

## Recover an interrupted overwrite

First use **Retry upload** in the original browser tab. If that tab is no longer
available, an operator can inspect and finish the staged operation with the
application command below. Use the same source revision and incoming storage
as the affected deployment. This is an upload recovery operation, not a schema
migration, and it does not rerun QC or change submitted artifacts.

Locate the owner's `INCOMING_DIR/<username>/uploads/<upload-key>/.overwrite`
journal. The upload key is the 64-character staging directory name; the journal
records `original_id`, `replacement_id`, file identities and the upload
descriptor. Use the original delivery ID, including a retired record:

```bash
python3 -m qc_tool.frontend.manage recover_delivery_overwrite \
  --delivery-id <original-id> --upload-key <upload-key>
```

The default prints an inspection summary without publishing or changing rows.
Review its owner, filename and replacement identity, then finish that exact
operation by repeating the command with `--apply`. The command validates the
journal's identity, locks the filename, and uses the same recovery service as
browser retries. A successor that already committed is confirmed once; a newer
unrelated delivery is never adopted. If the staged archive is incomplete or the
journal fails validation, preserve the files and investigate the storage error.
Do not delete the journal, receipt, `.previous` archive or filename reservation
to make an error disappear. Back up incoming storage with its recovery metadata
and apply the deployment's retention policy to archived inputs.

## Presentation and accessibility

`qcUpload.createFile(list, options)` returns a row with `.update(value)`.
Options include the filename, size, announcement region, optional detail and
action callbacks. Updates provide a state, readable label, percentage or `null`,
message and optional record link. State names include `selected`, `checking`,
`replaceable`, `queued`, `uploading`, `saving`, `paused`, `completed`, `failed`, `blocked` and
`canceled`. The component presents these states; adapters establish their truth.

Keep the main row ordered as file icon, filename, size, primary action and
Remove. New-file and replacement actions occupy the same primary-action position;
unavailable actions remain hidden. The Remove label means removal from the upload list.
Use the shared decorative file icon, hidden from assistive technology, and keep
the full filename as text. Put status, warnings and record links in the
secondary feedback area so they do not compete with the main row's actions.

Rows respond to the upload list's available width, including narrow cards on
wide screens. At narrow widths the actions move beneath the filename and size.
Allow long filenames to wrap and keep file sizes together. Preserve the action
order in the DOM so keyboard navigation follows the visible arrangement.

Use one progress bar per active file and hide it when the result is confirmed.
Completed rows retain their result and record link. Percentages describe measured transfer, not
server-side validation. Use `percent: null` for unmeasured processing. Never
infer success from 100% transferred or a vendor's generic queue-complete event.
Keep filenames and server messages as text, and supply links from trusted routes.

The shared picker associates guidance and errors with both its input and visible
chooser. It preserves a selected file when text is dropped on it. Queue mode
uses `deferValidation` so it can report invalid files individually while accepting
valid files from the same selection. Single-file adapters keep immediate picker
validation and clear rejected replacements through `onInvalid`.

Announce state changes instead of every percentage update. Retry preserves
keyboard focus on its file row when its button disappears; removal returns focus
to the chooser. File rows are not extra Tab stops. Shared styles support narrow
cards, long filenames, reduced motion and forced colors.

Single-operation adapters use `setBusy` to lock selection while processing.
Within their picker root, `data-upload-idle` marks controls hidden during work,
and `data-upload-pending hidden` marks pending guidance. A navigation link must
not suggest it can cancel a committed server operation. Interrupted responses
may leave activation completed without confirmation; describe that uncertainty.

## Verification

```bash
node --test src/qc_tool/frontend/dashboard/tests/javascript/*.test.cjs
```

CI and the optional Python wrapper discover all suites. Check shared behavior
with every adapter, including keyboard selection, mixed valid/invalid files,
individual/batch actions, duplicates, partial failures, retry, session expiry and removal.
Exercise slow transfer and server processing, product single-file no-JavaScript
fallback, boundary explicit activation, narrow cards and long filenames.

[layout]: ../../src/qc_tool/frontend/dashboard/templates/dashboard/layouts/upload_page.html
[queue-layout]: ../../src/qc_tool/frontend/dashboard/templates/dashboard/layouts/upload_queue_page.html
[picker]: ../../src/qc_tool/frontend/dashboard/templates/dashboard/shared/uploads/picker.html
[queue-template]: ../../src/qc_tool/frontend/dashboard/templates/dashboard/shared/uploads/queue.html
[helpers]: ../../src/qc_tool/frontend/dashboard/static/dashboard/js/shared/uploads.js
[queue]: ../../src/qc_tool/frontend/dashboard/static/dashboard/js/shared/upload-queue.js
[styles]: ../../src/qc_tool/frontend/dashboard/static/dashboard/css/ui/uploads.css
[products]: ../../src/qc_tool/frontend/dashboard/static/dashboard/js/features/products/upload.js
[deliveries]: ../../src/qc_tool/frontend/dashboard/static/dashboard/js/features/deliveries/upload.js
[boundaries]: ../../src/qc_tool/frontend/dashboard/static/dashboard/js/features/boundaries/upload.js
