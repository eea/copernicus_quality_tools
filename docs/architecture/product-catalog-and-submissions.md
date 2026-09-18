---
title: Product catalog and submissions
parent: Architecture
nav_order: 6
---

# Product catalog and submissions

The submission lifecycle answers three different questions without conflating
them:

1. What product units are expected for this immutable product release?
2. Which validated ZIP candidates have users published for each expected product unit?
3. Which candidates have assigned product managers or administrators approved?

`ProductUnit.product_unit_code` records the declared scope; it answers the first question
when its release is authoritative. It is never created from a delivery filename
or worker observation.
`Job.submitted_product_unit_code` answers what QC verified inside one ZIP.
`DeliverySubmission` links an exact successful Job to an exact ProductUnit and
stores immutable snapshots of both values.
Job and submission provenance also snapshots the requesting/submitting user,
API-token identifier, and token name. Token identifiers are intentionally not
foreign keys: deleting a credential must not rewrite historical audit facts.

## Relational ownership

The central [application schema](../../src/qc_tool/database/SCHEMA.md) maps these
models to the `catalog_*`, `execution_*` and `publication_*` tables in one database.

```mermaid
erDiagram
    Product ||--o{ ProductRelease : versions
    ProductRelease ||--o{ ProductUnit : expects
    ProductRelease ||--o{ ProductReleaseDefinition : executes
    QcDefinition ||--o{ ProductReleaseDefinition : snapshots
    Delivery ||--o{ Job : validates
    Delivery ||--o| DeliverySubmission : publishes
    Job ||--o| DeliverySubmission : authorizes
    ProductUnit ||--o{ DeliverySubmission : receives_candidates
    ProductUnit ||--o| SubmissionConflict : reviews
    SubmissionConflict ||--o{ SubmissionConflictEvent : audits
    DeliverySubmission ||--o{ SubmissionReviewEvent : decisions
```

One-to-one constraints ensure a Delivery and its authorizing Job can each
produce at most one durable submission. There is intentionally no uniqueness
constraint from `DeliverySubmission` to `ProductUnit`: multiple users must be
able to publish competing candidates without overwriting one another.

## Catalog ownership

Definitions describe executable QC checks. Reviewed recipes enter through
directory import from `product_definitions/` or the administrator upload
page at `/products/upload/`. `QcDefinition.document` stores the full imported
document as PostgreSQL JSONB; its digest identifies the original file bytes.
Recipes remain flexible while products, release links and expected product units have
relational identities and constraints.

`sync_product_definitions` imports a directory inventory into immutable
definition revisions. It creates one business product per canonical filename
stem and an initial release stream `definition:<ident>`. A consistent finite
naming product unit list becomes a draft scope; missing, wildcard or empty lists remain
unknown. These records make definition attributes and declared product unit counts
queryable without implying that a delivery plan has been approved.

Browser uploads use the same product/release representation and scope rules.
The page stages selected JSON files in a review queue. **Add** sends one file;
**Add all** sends the ready files sequentially, with a separate result for each.
Identical specifications are explicitly reported as already added. Failed files
remain retryable without removing earlier successful additions.
Only administrators can upload versions or remove specifications. A new filename
adds a product; changed bytes with an existing filename create its next immutable
release revision with an automatically recorded creation date. The first upload
of an imported recipe creates an upload-managed release even if its bytes match;
repeating the current uploaded file does not create another revision. The browser supports one matching
definition in one release stream; grouped specifications and multiple streams
require the reviewed manifest workflow. Queued or running jobs block uploads
and removal so the recipe cannot change during their execution.

Uploaded bytes are retained in shared
`WORK_DIR/product_definitions/.versions/<ident>/<digest>.json`; an atomic
`.state/<ident>.json` selects the current version. Catalog records are committed
before switching runtime state, and new QC requests verify that the active
digest matches the uploaded catalog revision. The page reports success only
after both stores are ready. Identical retries can finish activation after a
storage failure. The actor, action and digest are recorded in Django's admin
log. Back up the database and all shared specification bytes and state together.

Removal sets `Product.is_active` to false and publishes an inactive runtime
marker. This hides the product from active reports and QC selectors while
retaining its version history, jobs and final submissions. Directory imports
cannot reactivate it. Uploading the same filename restores it through a new
release revision; its product unit scope again requires review. If removal cannot publish
the marker after committing, the database product remains inactive and the
operator retries removal once storage is available.

A legacy `aoi_codes` naming parameter is not automatically an authoritative completion
plan. For example, CLC accepts individual country codes and combined-country
codes that can represent alternative delivery groupings. Administrators use
**Products → product → Set up delivery plan** to approve explicit expected product units
and assign product managers. A changed scope creates a new revision; changing
only managers preserves the existing plan and its approved progress. Historical
submissions remain attached to their original plan. The browser records the
approving administrator and rejects stale plan or assignment forms.

A reviewed `sync_product_catalog` manifest can also define business grouping and
authoritative scope. It supplies explicit `product_unit_codes`, or a `source_definition` only when that
entire finite list is the intended delivery plan. Wildcards cannot define a
denominator.

`ProductRelease.source_kind` records whether a scope comes from directory import
(`definition`), browser upload (`upload`) or a reviewed manifest (`manifest`).
Directory import never replaces uploaded or curated scopes, including draft
scopes, or reactivates archived products. Browser plan approval retains the
specification's source kind and protects its authoritative scope from directory
imports. A manifest can approve an imported or
uploaded stream by supplying a higher revision of the same `definition:<ident>` key. A different
key represents an additional stream, not a replacement.

Both import services validate input before writing, normalize and deduplicate
product units, and use the same PostgreSQL transaction advisory lock. They create complete
immutable revisions before moving current pointers. Changed catalog content
creates a higher revision linked to its predecessor; unchanged imports are
idempotent. Removing a recipe file never deletes historical catalog rows.

The [product definition guide](../development/product-definitions.md) owns the
commands, reviewed manifest example, JSONB queries and rollout procedure.

## Job and submission lifecycle

```mermaid
sequenceDiagram
    actor User
    participant UI as Browser or API
    participant DB as PostgreSQL
    participant Worker
    participant Store as Submission storage
    actor Manager as Product manager

    User->>UI: Upload ZIP for one product unit
    UI->>DB: Create Delivery
    User->>UI: Request QC for explicit definition
    UI->>DB: Create Job + actor/definition/release snapshot
    Worker->>DB: Claim and complete Job
    Worker-->>UI: result.json with product_unit_code
    UI->>DB: Store submitted_product_unit_code + result metadata
    User->>UI: Submit delivery
    UI->>DB: Lock Delivery/latest Job and reserve DeliverySubmission
    UI->>Store: Copy to private staging directory
    UI->>Store: Atomic rename to submission UUID path
    UI->>DB: Finalize published record and legacy timestamp
    DB-->>Manager: Await review for the assigned product
    Manager->>UI: Approve or decline with feedback
    UI->>DB: Check product scope and review version
    DB->>DB: Append review event; update decision
    Note over DB,Store: Published files and receipt remain unchanged
```

Browser and API endpoints are thin adapters over the same service. Reservation
requires the deterministically latest Job to be successful, to contain one
canonical submitted product unit, and to reference an authoritative release and exact
QC definition revision. It also requires a valid SHA-256 snapshot binding the
archived input to the exact ZIP inspected by QC. S3 registration and QC remain
available, but final submission rejects remote inputs with `s3_input_not_archived`
because their source objects are not copied into publication storage. Upload the
ZIP and run QC on that upload before publishing a retained deliverable. A successful
older Job never overrides a newer failed or running Job. Once a Job reaches a
terminal state, later polling cannot rewrite its terminal status, product unit, result
metadata, or input digest.

Workers resolve the shared active-version marker when execution starts. The
selected immutable file overrides configured recipes; an inactive marker hides
the product, and missing or corrupt active files never fall back to another
version. Without a marker, configured directory precedence applies.
The Job's database definition reference records provenance but does not supply
the worker's configuration. Deploy matching frontend/worker recipes and drain
queued and running jobs before changing their files; otherwise a queued Job can
execute different content from its stored snapshot.

Publication uses a deterministic directory keyed by the server-generated
submission UUID. Files are copied without following symbolic links into a
same-filesystem staging directory. A manifest records the delivery, Job,
release, both product unit values, input checksum, and hashes of published files. One
atomic rename exposes the complete directory. A retry accepts an existing
directory only if its bounded manifest identifies the same submission and
the no-follow file inventory still matches every recorded path, size, and
SHA-256 digest. Files and directory entries are synchronized before the database
records success. Retries of finalized submissions also check the stored manifest
digest against the database receipt. A mismatch produces an integrity error and
leaves the retained files in place for investigation.

The database and filesystem form a recoverable saga:

- failure before rename leaves a `failed` submission that can be retried;
- failure after rename is recovered by the deterministic manifest;
- no failure path clears `Delivery.date_submitted`;
- finalization writes the exact same timestamp to the durable submission and
  legacy Delivery field;
- PostgreSQL rejects a `published` row without publication and input digests;
- one Delivery and authorizing Job have at most one DeliverySubmission;
- many deliveries may point to one ProductUnit.

Ordinary model and queryset operations cannot delete submission history or
rewrite finalized receipt fields. Review and conflict events are append-only;
the current review state and version change through the review services. The retained ZIP and reports
remain available independently of upload and worker-scratch cleanup. Storage
permissions, consistent database/storage backups and restore verification are
required operational safeguards; see [retention](../../src/qc_tool/database/SCHEMA.md#retaining-verified-deliverables).

## Submission review

Publication and approval are independent. A successfully stored submission starts
as **Awaiting review**, including submissions made by an administrator. Successful
QC and safe storage do not approve a delivery automatically. The uploader can
follow the submission's status and feedback; an assigned product manager or an
administrator reviews it in the submission pages.

The reviewer can approve a published candidate or decline it with a required
reason. An archived product cannot receive new approvals. A declined delivery's
ZIP, reports and receipt remain available; the user submits corrections as a new
delivery with a new successful QC job. Review services record every decision in
`SubmissionReviewEvent`, including the actor's retained username, timestamp,
notes and submission review version. An outdated form cannot overwrite a newer
decision.

The **Deliveries** page distinguishes QC results from the manager's decision.
Its primary navigation follows the uploader's workflow:

| View | Membership and next step |
| --- | --- |
| **Action required** (default) | **Review changes** for requested corrections; **Resolve QC issues** for failed checks; **Run QC** for unvalidated uploads; **Submit** for passed checks. These groups always appear in that order, before pagination. |
| **Running now** | Queued or running QC jobs. The badge distinguishes **In queue** from **In progress**; the view link is quiet and the activity indicator respects reduced-motion preferences. |
| **In review** | Submitted deliveries awaiting a manager's decision, including competing submissions under review. |
| **Completed** | Published submissions explicitly accepted by a manager. These remain searchable as history. |

**All deliveries** is a secondary view for searching across the entire workflow.
Status badges describe the delivery inside its stage; backend status names are
not the main navigation. Search, product and product unit filters apply to every view and
update their counts. Search and sorting sit directly below the workflow tabs.
**Filters** expands Status, Product and product unit controls in the same table area,
and shows how many of those filters are applied when collapsed. **Clear filters**
appears only while a filter is applied and keeps the selected workflow.
Exports use the current workflow, filters and ordering. Column sorting within
**Action required** preserves the action groups and sorts within each group.

The page refreshes QC and review changes while visible, preserving row selections
and keyboard focus. Finished checks move from **Running now** to **Resolve QC
issues** or **Submit**. Submission moves the delivery to **In review**; acceptance
moves it to **Completed**, while rejection returns it to **Review changes**.
Published rejections show **Correction needed**, with the current feedback,
reviewer and date. **View feedback** opens
the retained submission and its full review history. The uploader's **My
submissions** page includes completed decisions by default; the manager's queue
defaults to work awaiting review.

To request a correction, the manager chooses **Reject and request corrections**
and writes the changes needed in the feedback field. The uploader then:

1. Opens **View feedback** from Deliveries and checks the requested changes.
2. Chooses **Upload correction** and prepares a corrected ZIP with the exact
   original filename, including letter case. The correction page accepts only
   this filename and checks that the rejected submission still belongs to them.
3. Chooses **Upload correction**, then **Run quality checks** and checks the same
   product and product unit. After QC passes, they choose **Submit for review**.
   Uploading alone does not request review.

The corrected delivery is a new submission for its product and product unit. Managers can
compare it with the other retained submissions for that product unit. The rejected receipt
remains rejected in the history; it is not silently replaced or approved when a
new file arrives. A correction creates a fresh delivery while preserving the
original ZIP, QC evidence and review events. The upload page's `correction_for`
parameter supplies authorized feedback and identifies the rejected submission.
The preflight and upload endpoints require that identity, the original delivery
identity and the unchanged filename; a changed review state or upload target
prevents the correction. This workflow does not introduce a separate persistent
revision relationship.

Review visibility and correction eligibility are shared by the submission and
upload workspaces through `services/submissions/access.py` and `presentation.py`.
The delivery listing joins only the current review event, so a stale comment
cannot represent a newer decision. Review comments are available to the uploader,
assigned product managers and administrators; broader delivery browsing grants
do not expose this correspondence.

Product-manager review scope is the canonical **business product** assigned to
the manager. A grant for another recipe, a region grant or visibility of an
uploader's other files does not grant review authority. Administrators can review
all products. Submission itself remains restricted to the delivery owner or an
administrator; reviewing a user's delivery does not make the manager its owner.

## Competing submissions and coverage

Several deliveries, including deliveries from the same user, may target one
ProductUnit. Unreviewed competitors open one durable `SubmissionConflict`; no
candidate overwrites another. Approving one candidate selects it and records why
the others were declined. Declining every candidate closes the conflict without
contributing to fulfilment.

A newly published competitor does **not** revoke an existing approval. The
approved delivery continues to count while the other submission awaits review.
Replacing it is an explicit reviewer action with a required explanation.
Replacement appends approval/decline events for the affected candidates and a
conflict-resolution event; all earlier decisions and files remain. Every new
candidate or review change advances the conflict version, so a reviewer must
refresh if the candidate set changed after the page was loaded.

Publication and review acquire the product unit row before locking its submission
candidates. Review also participates in the catalog transaction lock, serializing
decisions with product removal and plan changes. This prevents simultaneous
decisions from approving competing candidates through stale projections.

Coverage counts distinct expected ProductUnit rows, never submission rows:

- `declared_expected`: product units declared in draft or authoritative scopes;
- `expected`: product units in an authoritative release;
- `accepted`: product units with a published, approved candidate;
- `conflicts`: product units with unresolved competing candidates;
- `remaining`: expected minus accepted.

The `accepted` field counts units with an accepted delivery. Open conflicts can coexist with an approved
candidate and therefore do not subtract an existing contribution.

Draft scope counts support planning and are labeled separately in `/products`.
Expected, accepted and completion figures remain unavailable until the scope
is authoritative. Unknown scopes have no finite count. Product-level totals
combine current release streams and remain unavailable if any included scope
does not supply the required denominator. Duplicates cannot inflate completion.

## Final product readiness

Complete accepted coverage enables a separate manager action; it never marks
a product ready automatically. The shared readiness service evaluates every
current stream and requires authoritative, nonempty plans with every unit
accepted. An assigned manager or administrator confirms the exact current
scope from the product page. The product retains the confirmation timestamp,
actor snapshot and scope fingerprint; Django admin history retains the action.

Catalog revisions, acceptance changes and product removal invalidate readiness
and old confirmation forms. Restoring an earlier state cannot resurrect its
old final approval. Finalization, review and catalog edits use the same catalog
transaction lock.

## Deployment order

```bash
python3 -m qc_tool.frontend.manage database apply
python3 -m qc_tool.frontend.manage sync_product_definitions path/to/definitions --dry-run
python3 -m qc_tool.frontend.manage sync_product_definitions path/to/definitions
python3 -m qc_tool.frontend.manage sync_product_catalog path/to/catalog.json --dry-run
python3 -m qc_tool.frontend.manage sync_product_catalog path/to/catalog.json
python3 -m qc_tool.frontend.manage backfill_product_unit_metadata --dry-run
python3 -m qc_tool.frontend.manage backfill_product_unit_metadata --batch-size 100
```

Paths above refer to reviewed files visible in the frontend runtime; use the
full [operator workflow](../development/product-definitions.md#deploy-and-maintain)
for the target deployment and matching worker recipes. Catalog synchronization
is an explicit operation. Migrations never read product definitions or shared
result files. Historical legacy submissions
remain fail-closed until they are reconciled; the new service does not guess an
authorizing Job or expected release.

Run the schema command as the serialized deployment job described in
[Operations](../deployment/operations.md#upgrades). The major architecture
release requires a new database and an operator-managed import; these commands
do not perform that transfer. See
[Database migrations](../development/database-migrations.md).
