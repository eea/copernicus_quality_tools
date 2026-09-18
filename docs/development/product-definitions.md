---
title: Product definitions
parent: Development
nav_order: 4
---

# Product definitions and reporting

The product catalog starts empty. Administrators add reviewed JSON specifications
through **Products → Upload specification** and manage their versions there.
Bundled files in `product_definitions/` are reference recipes; their presence does
not make them available in the catalog, product grants, or QC selectors. Startup
and database initialization never import them.

An operator can also explicitly import a reviewed directory inventory. Uploads
and imports store immutable documents in PostgreSQL to query parameters and report product coverage.
Keep the operational delivery plan explicit: a naming check's accepted product units
do not necessarily describe the deliverables that must be submitted.

## Sources and responsibilities

| Source | Responsibility |
| --- | --- |
| JSON files in `product_definitions/` or configured `PRODUCT_DIRS` | Reference recipes and execution files for explicitly imported products; never automatic catalog entries |
| `WORK_DIR/product_definitions/.versions/<ident>/<digest>.json` | Immutable original bytes of uploaded specifications, shared by frontend and workers |
| `WORK_DIR/product_definitions/.state/<ident>.json` | The active uploaded version or an archive marker used by runtime discovery |
| `catalog_definition_revision.document` | Complete imported recipe, stored as PostgreSQL `jsonb` |
| `catalog_definition_revision.digest` | SHA-256 of the original file bytes, identifying that revision |
| `catalog_product` and `catalog_release_revision` | Product identity and active status, dated revision history, scope ownership and selected release scope |
| `catalog_release_definition` | Exact definition revisions belonging to each release |
| `catalog_product_unit` | Normalized, deduplicated product units for a release's declared or approved scope |
| Reviewed catalog manifest | Business grouping and authoritative expected-delivery plan |

The document stays flexible because different QC checks need different
parameters. Relationships, identities and coverage product units are relational so they
can be constrained and aggregated. Do not split arbitrary check parameters into
generic key/value tables or edit imported snapshots directly in pgAdmin.
[Django's JSONField](https://docs.djangoproject.com/en/5.2/ref/models/fields/#jsonfield)
uses PostgreSQL `jsonb`; [PostgreSQL JSON types](https://www.postgresql.org/docs/14/datatype-json.html)
explain its storage and indexing behavior.

The digest identifies source bytes, not a reserialization of `document`:
whitespace changes also produce a new revision. JSONB does not preserve original
formatting or numeric notation. Integrity checks use database JSON equality so
equivalent exponent and expanded numeric values do not create false collisions.
Keep the reviewed source commit with deployment evidence. The stored
`source_path` is import provenance; moving an identical file does not create a
different definition or require that path to exist when querying the database.

## Declare required product units

Use an explicit top-level list in the product specification:

```json
"product_units": ["unit-001", "unit-002", "unit-003"]
```

This member belongs alongside `description` and `steps` in the complete JSON
specification. Codes are case-insensitive, trimmed identifiers; numeric padding
and suffixes are preserved. The list creates a draft scope for administrator
approval. If finite geographic naming rules also exist, the declared units must
be supported by them. Legacy naming checks keep `parameters.aoi_codes` unchanged;
the import adapter translates their geographic identifiers into product units.
A required unit is always tied to one immutable release revision.

## Add or update a product in the browser

1. Sign in as an **administrator**. Uploading and removing specifications require
   the administrator role; configuration or product-management permissions alone
   do not authorize these actions.
2. Open **Products → Upload specification** (`/products/upload/`), or choose
   **Upload revision** on an existing product. Choose or drop reviewed JSON
   specifications. Review their file rows, then select **Add** for one file or
   **Add all** for the ready files. Each request validates and saves one file;
   a failed file does not remove successful additions. An identical existing
   specification is explicitly marked **Already added**.
3. After success, use **View product** to inspect its dated version history.
   The product is also available in the QC product selector. Run a
   representative delivery through its checks before assigning it to users.
4. Review the declared product units and use the [delivery-plan procedure](#approve-a-delivery-plan)
   when its expected deliverables are ready for approval. Uploading a recipe
   creates a draft or unknown scope; it does not approve final submissions.

The filename becomes the lowercase product identifier. Use a stem of
1–64 ASCII letters, digits, dots, underscores or hyphens, starting with a letter
or digit, followed by `.json`. `list` and `upload` are reserved. The limit is
**1 MiB per file**. JSON must be UTF-8, contain a nonempty description and at
least one QC step, and have no duplicate keys or non-finite numbers. Each step
must name an installed `qc_tool.raster.*` or `qc_tool.vector.*` check and declare
`required` as a Boolean; existing numeric `0`/`1` flags are accepted too.
Parameters and naming product units pass the same catalog validation as directory imports.
Validation checks the specification structure; use representative QC fixtures to
verify that its check parameters implement the intended product rules.

Use a new filename for a new product. To update an existing product, upload the
revised JSON with the **same filename**: its identity stays stable while changed
bytes create the next immutable release revision. QC Tool records the creation
date automatically; a date in the filename is unnecessary. The first upload of
an imported specification creates an upload-managed release even when its bytes
match the imported file. Repeating the current uploaded file without byte changes
is a no-op, apart from completing an interrupted runtime activation. Previous
definitions, releases, jobs and submitted
deliverables retain their original references. The administrator, action and
source SHA-256 digest are recorded in Django's admin log.

The browser workflow supports a product with one release stream and one matching
definition. Products grouping several specifications or release streams require
the [reviewed catalog manifest](#approve-a-delivery-plan) workflow. Uploading a
changed recipe derives a fresh draft or unknown product unit scope; it does not carry an
older scope's business approval forward. Upload and removal operations are
blocked while the specification has queued or running QC jobs. Let those jobs
finish before trying again.

## Remove and restore a product

An administrator can choose **Remove specification** from the product detail
page and confirm the action. Removal sets `catalog_product.is_active` to false
and publishes an inactive runtime marker. The product is hidden from active
product lists and QC selection. It keeps its dated revision history, database
references and stored version files; submitted deliverables remain intact.
Directory synchronization does not reactivate a removed product.

Find it under **Removed products**, open its detail page, and select
**Restore product** to upload a specification with the same filename. Restoration
creates a new release revision, reactivates the product and selects the uploaded
bytes for future QC. Review its product unit plan again before approving submissions.
Grouped products and products with queued or running jobs follow the same
restrictions as version uploads.

## Runtime storage and recovery

The original bytes are stored under
`WORK_DIR/product_definitions/.versions/<ident>/<digest>.json`;
`source_path` records `upload:<ident>.json`, and the release's `source_kind` is
`upload`. Frontend and workers must mount the **same persistent WORK_DIR** with
compatible access permissions. An atomically written
`.state/<ident>.json` selects the active digest or disables that identifier.
State is checked on each read, so additions, version switches and removals need
no process restart. Active version state takes precedence over configured
`PRODUCT_DIRS`; an inactive marker prevents a bundled recipe from reappearing.
Without version state, configured directory precedence still applies to recipe
resolution. The application only offers active products registered in the
database catalog; a recipe file alone cannot enable new product work. The
repository's `product_definitions/` remains unchanged.

Catalog records are committed before immutable runtime bytes are published and
the active pointer is switched. The page reports success only after both stores
are ready. New QC requests check that the selected runtime digest agrees with
the current uploaded catalog revision. Missing, corrupt or mismatched active
versions cannot silently fall back to another recipe. If activation fails after
the database commit, correct the storage problem and upload the same original
file again to complete it. If removal fails while updating storage, the database
product remains inactive; retry removal after restoring storage access.

Do not delete catalog rows, edit pointers manually or substitute different bytes
to recover an interrupted operation. Keep a backup of **both the database and
the shared uploaded-specification directory**, and preserve it during worker
scratch cleanup, including its hidden `.versions` and `.state` directories.

## Optional operator import

Use the administrator upload page for normal product setup. Directory import is
an explicit bulk operation, never an installation or startup step. Import only
the reviewed files intended for this catalog; importing the entire bundled
directory creates a product for every recipe in it.

Start the [local environment](../getting-started/local-development.md) and verify
that its schema is ready. Put the selected JSON files in a directory visible to
the container. From the repository root, preview that directory's import:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage sync_product_definitions \
  /path/in/container/to/reviewed-specifications --dry-run
```

After reviewing the output, apply it and check that repeating the import would
make no changes:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage sync_product_definitions \
  /path/in/container/to/reviewed-specifications

docker compose -f docker/compose.local.yaml run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage sync_product_definitions \
  /path/in/container/to/reviewed-specifications --check
```

Pass additional directory arguments when importing more than one recipe source.
Use paths visible inside the container, and ensure the frontend and workers use
the same effective recipes. `--dry-run` previews without persisting changes;
`--check` makes no changes and returns a nonzero exit status when synchronization
is needed. Both validate the input. Missing or invalid definitions must be fixed
before applying; a failed import must not be treated as a partial success.
The command reads `*.json` files directly in each directory. Duplicate canonical
identifiers across the selected directories are rejected; provide one effective
file per recipe instead of relying on directory precedence. Definitions are
limited to 1 MiB each and an import to 5,000 definitions. Duplicate JSON keys and
non-finite JSON constants are rejected. Existing Boolean and numeric `0`/`1`
check flags are retained in the stored document.

All selected definitions are validated before writes. Application uses one
transaction and the same PostgreSQL catalog advisory lock as
`sync_product_catalog`. The import:

1. Stores each new definition revision without changing older documents.
2. Creates a business product for each canonical filename stem, with a default
   release stream named `definition:<ident>`.
3. Projects a consistent, finite, nonempty naming product unit list into a `draft` scope.
   Missing, wildcard or empty lists produce `unknown` coverage. Invalid codes
   or naming checks that disagree require correction.
4. Creates a higher revision when an automatically managed scope changes.
   A reviewed manifest's current scope is preserved; importing a changed recipe
   does not silently replace curated release definitions or approved product units.
5. Retains previous revisions and records whose source files have been removed.

`ProductRelease.source_kind` distinguishes directory-managed (`definition`),
browser-uploaded (`upload`) and manifest-managed (`manifest`) scopes. Directory
imports preserve uploaded and curated scopes, including draft scopes. A reviewed
manifest can approve either stream with a higher revision. Directory imports
also retain inactive products without reactivating them.

Schema initialization and application startup do not import recipes. This is a
catalog data operation and does not generate migration files. Use
[`database plan|check|apply`](database-migrations.md) for schema changes.

## Interpret `/products`

Each row represents one product. Select its name to open the specification
history and release details. Search by name or identifier, or filter by delivery
plan status. **Export CSV** exports the filtered rows. Administrators can upload
specifications and switch between **Active products** and **Removed products**.

**Required product units** shows the required product units, with provisional values
identified as such. **Accepted coverage** shows accepted, published units out of
the approved total, rather than the number of uploaded files. Draft, undefined
and mixed plans explain why coverage cannot yet be calculated. Restricted
coverage stays hidden, including its plan status. **How to read this table**
explains the counting rules on the page.

| Scope | What the report means |
| --- | --- |
| Draft scope | Declared product unit count is available for planning; authoritative expected/completed counts are unavailable |
| Authoritative scope | Required product units are approved; accepted, conflicting, remaining and completion figures can be calculated |
| Unknown scope | No finite denominator is available; unavailable counts remain null |

`declared_expected` counts product units in draft or authoritative scopes. It does not
authorize submission. If a product has multiple current release streams, the
product totals combine their scopes; an unknown stream prevents a complete
product denominator. The report counts expected delivery slots across releases,
so the same product unit in two distinct releases represents two slots.

Active product reports omit products with `is_active = false`. Their detail and
version history remain available to authorized users for historical review.

Managed product details link every definition to its stored JSON revision using
its identifier and source digest. These authenticated links continue to work
after the source file changes or disappears. The response reserializes JSONB;
its bytes are not the original file and do not have that source digest. The
definition endpoint without a `digest` query parameter still returns the current
executable file used by the file-based workflow.

For example, [`clc2024.json`](../../product_definitions/clc2024.json) accepts both
`be`, `fr`, `lu`, `nl` and the combined `be_fr_lu_nl`, and both `cz`, `sk` and
`cz_sk`. These may be alternative delivery groupings. Counting every permitted
name as a required delivery would overstate the workload. Review the actual
delivery plan before promoting the scope.

## Approve a delivery plan

Administrators activate delivery plans in the browser. Product managers review
submitted deliveries; uploading a specification or passing QC alone does not
approve either a plan or a delivery.

1. Open **Products**, select the product name, and choose **Set up delivery
   plan** in its **Delivery plans** card. An already approved plan has an
   **Update delivery plan** action instead.
2. Enter the expected product unit codes, one per line or separated by commas. Imported
   finite scopes are prefilled. Select the actual contracted delivery areas;
   permitted naming alternatives are not necessarily additional deliverables.
   Every listed product unit must be supported by a linked specification. Wildcard
   specifications still need an explicit expected product unit list for progress reports.
3. Select the product managers responsible for the product. Accounts must have
   the `product_manager` role before they appear here; use **Admin panel →
   Users** to assign that role. Assignments apply to the whole product, including
   its release streams. Administrators can review even without assigned managers.
4. Confirm the plan and select **Approve and activate plan**. Its status becomes
   **Open for submissions**. The product page shows expected and approved product units,
   and assigned managers can open **Review submissions**.

Changing the product unit set creates an immutable plan revision. Submissions and
approvals remain attached to their original revision and do not automatically
fulfil the new plan. Review this consequence before changing an active scope.
Changing only the assigned managers preserves the current plan and progress.
A stale form is rejected; reopen the current plan before retrying.

A QC job run before plan approval can be submitted against the current plan
when that plan still contains the exact specification used by the job and the
verified product unit. A changed specification requires a new QC run. Historical QC jobs
and submission receipts retain their original references.

### Submit, review and follow up

| Role | Workflow |
| --- | --- |
| Administrator | Upload/create, revise or remove products; approve delivery plans; assign managers; review submissions for any product |
| Product manager | Open assigned products and their progress; verify retained delivery files and QC evidence; approve or decline submissions |
| User | Upload a delivery, run QC, submit a successful result for review, and read decisions on their own submissions |

1. The user uploads a ZIP through **Deliveries → Upload delivery**, selects its
   product specification and runs QC. Once it passes, choose **Submit for
   review** on the delivery row. The product must have an approved plan, and the
   verified product unit must belong to it. Submission storage must be configured by the
   deployment operator.
2. QC Tool stores the ZIP and QC evidence, then marks the receipt **Awaiting
   review**. This does not yet count towards product fulfilment. The delivery's
   **View submission** link and **My submissions** navigation show its status.
3. An assigned manager or administrator opens **Submissions**, selects a delivery,
   and downloads its retained files to verify them. File downloads enforce
   product/owner access and compare their checksums with the stored receipt.
   Use **Approve submission** or **Decline submission**. A decline requires
   feedback describing what the uploader should correct.
4. Approval counts the product unit once for that plan. If there are competing
   submissions, explicitly choose **Approve this and decline competing
   submissions** and explain the selection. A previous approved delivery keeps
   contributing until a reviewer replaces it. Concurrent decisions invalidate
   stale review forms.
5. The uploader can read the decision and notes under **My submissions**; use
   its status filter to find approved or declined items. To correct a decline,
   upload a new ZIP, run QC and submit again. Original files, receipts and dated
   review decisions remain retained, including after product removal or worker
   scratch cleanup.

### Confirm the product is ready

After all required units have accepted deliveries, open the product detail
page and select **Mark product ready**. This final action requires an assigned
product manager or administrator. Full accepted coverage alone leaves the
product awaiting confirmation. All current release streams must have approved,
nonempty plans; the action checks the whole product, not only visible rows.

The product records who confirmed it and when. Changing its current plan,
reversing or replacing a relevant acceptance, or archiving the product clears
readiness. Review the changed product and confirm again after its requirements
are fulfilled. Stale confirmation forms cannot finalize a changed scope.

### Maintain a reviewed catalog manifest

Keep the catalog manifest in version control with its review evidence. It can
group multiple definitions under one business product and explicitly list its
expected product units. Preserve the product identifier used for authorization grants;
changing business grouping also requires reviewing the granted report scope.

To replace an imported scope, use the same `definition:<ident>` release key and
a revision greater than every stored revision for that key. Inspect it in
pgAdmin first:

```sql
SELECT release_key, revision, source_kind, coverage_state, is_current
FROM catalog_release_revision
WHERE release_key = 'definition:clc2024'
ORDER BY revision DESC;
```

This illustrative manifest approves only the `CZ` delivery. Replace its product unit list,
description and revision with the reviewed plan; revision `2` applies only when
the highest existing revision is `1`:

```json
{
  "schema_version": 1,
  "products": [{
    "ident": "clc2024",
    "name": "CORINE Land Cover 2024",
    "description": "CORINE Land Cover 2024",
    "releases": [{
      "release_key": "definition:clc2024",
      "revision": 2,
      "description": "Reviewed CZ delivery scope",
      "is_current": true,
      "definition_idents": ["clc2024"],
      "primary_definition": "clc2024",
      "coverage": {"state": "authoritative", "product_unit_codes": ["CZ"]}
    }]
  }]
}
```

Use `coverage.source_definition` instead of `product_unit_codes` only when the entire
finite naming list has been reviewed as the delivery plan. The two product unit sources
are mutually exclusive. A separate release key represents an additional stream,
so it can add another denominator rather than superseding the imported scope.

Save the reviewed manifest at an actual path visible in the frontend container.
For example, if it is stored at `catalog/production.json` in the checkout:

```bash
docker compose -f docker/compose.local.yaml run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage sync_product_catalog \
  /usr/local/src/copernicus_quality_tools/catalog/production.json --dry-run

docker compose -f docker/compose.local.yaml run --rm --no-deps frontend \
  python3 -m qc_tool.frontend.manage sync_product_catalog \
  /usr/local/src/copernicus_quality_tools/catalog/production.json
```

Reimporting unchanged content is idempotent. Changing definition content or
coverage requires a higher reviewed release revision. Historical jobs and final
submissions retain their existing release/definition references. Do not delete
their catalog records to retire a recipe.

## Query definitions in pgAdmin

The following read-only examples target PostgreSQL 14. Definition identifiers
are stored in `product_ident`; that field identifies the recipe, while business
product identity lives in `catalog_product.ident`. Filter through current release
links when reporting current configuration. Selecting the latest `imported_at`
can accidentally select an unapproved revision.

This query selects each referenced definition revision once, even if multiple
current releases use it, and extracts nested naming parameters, reference years
and pixel sizes without assuming a step order:

```sql
SELECT d.product_ident, d.digest,
       jsonb_path_query_array(d.document,
         '$.steps[*] ? (@.check_ident like_regex "[.]naming(_pdf)?$").parameters'
       ) AS naming_parameters,
       jsonb_path_query_array(d.document,
         '$.steps[*].parameters.reference_year'
       ) AS reference_years,
       jsonb_path_query_array(d.document,
         '$.steps[*] ? (@.check_ident == "qc_tool.raster.pixel_size").parameters.pixelsize'
       ) AS pixel_sizes
FROM catalog_definition_revision AS d
WHERE EXISTS (
    SELECT 1
    FROM catalog_release_definition AS link
    JOIN catalog_release_revision AS r ON r.id = link.product_release_id
    JOIN catalog_product AS p ON p.id = r.product_id
    WHERE link.qc_definition_id = d.id AND r.is_current AND p.is_active
)
ORDER BY d.product_ident, d.digest;
```

Filter arbitrary nested attributes with containment. This finds current
definitions with a step declaring reference year `2024`:

```sql
SELECT d.product_ident, d.digest
FROM catalog_definition_revision AS d
WHERE d.document @> '{"steps":[{"parameters":{"reference_year":"2024"}}]}'::jsonb
  AND EXISTS (
    SELECT 1
    FROM catalog_release_definition AS link
    JOIN catalog_release_revision AS r ON r.id = link.product_release_id
    JOIN catalog_product AS p ON p.id = r.product_id
    WHERE link.qc_definition_id = d.id AND r.is_current AND p.is_active
  );
```

JSON strings and numbers differ: `"2024"` is not `2024`. For key-existence checks,
use a JSONPath such as `$.steps[*].parameters.boundary_source` with the `@?`
operator. Do not assume all check families use the same parameter names or units.
See [PostgreSQL JSON functions and operators](https://www.postgresql.org/docs/14/functions-json.html).

For product totals, aggregate normalized product units instead of expanding raw JSON
arrays. This preserves unknown/draft semantics and avoids multiplying product unit counts
by a release's number of linked definitions:

```sql
SELECT p.ident,
       count(DISTINCT r.id) AS current_release_count,
       CASE WHEN bool_and(r.coverage_state IN ('draft', 'authoritative'))
            THEN count(a.id) END AS declared_expected,
       CASE WHEN bool_and(r.coverage_state = 'authoritative')
            THEN count(a.id) END AS expected
FROM catalog_product AS p
JOIN catalog_release_revision AS r ON r.product_id = p.id AND r.is_current
LEFT JOIN catalog_product_unit AS a ON a.product_release_id = r.id
WHERE p.is_active
GROUP BY p.id, p.ident
ORDER BY p.ident;
```

Use the existing coverage service for published/completed totals: it also
accounts for unresolved candidate conflicts. Counting delivery or submission
rows alone can inflate completion. Direct SQL has database-role access, not the
browser's account/product authorization filters.

Add indexes only for measured query patterns. A GIN index can help JSONB
containment/path searches; a frequently aggregated business attribute may justify
a typed projection instead. Inspect query plans and representative data before
adding either through the central schema workflow.

## Deploy and maintain

1. Review recipes, expected product units, check implementation and representative QC
   fixtures together. Record the source commit and matched frontend/worker
   images in the [release record](../../src/qc_tool/database/RELEASE_TEMPLATE.md).
2. Before replacing executable files, stop accepting new QC requests and drain
   queued/running jobs. Workers load recipe files at execution time; the stored
   JSON revision is not their execution source. A job's database snapshot alone
   does not prevent a changed file from being used later.
3. Deploy matching recipes to frontend and worker runtimes. Run the
   [schema procedure](../../src/qc_tool/database/MIGRATIONS.md#prepare-a-release)
   where required, then the explicit definition import and any reviewed catalog
   manifest with one deployment operator. Never seed catalog data in migrations.
4. In production use the deployment's pinned frontend image and Compose settings,
   following the `qc_compose` setup in the
   [database runbook](../../src/qc_tool/database/MIGRATIONS.md#deployment-command-setup).
   Replace `docker compose -f docker/compose.local.yaml` in the examples with
   `qc_compose` and use the release's actual recipe/manifest paths.
5. Check import idempotency, inspect current definition digests and release
   links, and verify `/products` as an administrator and a scoped product manager.
   `sync_product_definitions --check` is not proof that a curated release uses
   the changed recipe; inspect that linkage and apply its higher manifest revision.
   Run a representative QC job before reopening normal intake.
6. Retain prior definitions/releases and published deliverables. Recipe deletion
   does not remove historical catalog rows. Recovery uses the reviewed source
   and release procedure; it must not rewrite immutable snapshots or job history.

Workers, job forms and recipe download endpoints select uploaded version state
when present, and otherwise read configured recipe files. Deploying only a
database import does not change their checks. Browser version uploads publish
their runtime bytes and active pointer as part of registration after checking
for active jobs; direct changes to deployed recipe files require the coordinated
deployment procedure above. See
[catalog and submission architecture](../architecture/product-catalog-and-submissions.md)
for the publication and coverage invariants.
