# Additive record import: identity and consistency audit

Research date: 21 October 2026. This appendix records a read-only code audit. It
does not describe an implemented general merge engine. No application model,
product specification, stored artifact or database was changed by this audit.

## Main finding

The maintained code has strong building blocks for safe transfer: complete graph
validation, explicit account mapping, private archive staging, byte-verified
artifact publication, a maintenance barrier, an execution lease and a receipt
committed with imported rows. The application importer nevertheless deliberately
requires empty QC business tables. Removing that single check would be unsafe:
identity allocation, publication evidence, reconciliation, repeated imports and
the conflict UI all currently depend on the empty-target rule.

A sustainable additive importer should plan changes to the **current database**,
with create, exact reuse and explicit exclusion decisions. A native PostgreSQL
backup remains a disaster-recovery product: restoring it into a separate
database and switching databases is not a merge and cannot fulfill an additive
import request.

The most important constraint is that some apparent database IDs are also
embedded in immutable evidence. Published submission manifests contain delivery,
release and unit IDs. Product readiness digests contain product and release IDs
and accepted-candidate aggregates. Reassigning every colliding integer ID and
rewriting foreign keys alone would break that evidence or falsely carry its
meaning into a different target scope.

## Evidence and current behavior

| Area | Observed implementation | Consequence for additive import |
| --- | --- | --- |
| Portable model contract | [`RESOURCE_FIELDS`](../../src/qc_tool/database/transfers/records.py) explicitly allowlists every managed dashboard model and its fields; `_assert_contract_registry()` refuses an unreviewed inventory change | Extend the central contract rather than accepting uploaded Django model/table names or adding another importer |
| Portable scope | `export_records()` exports selected accounts or the complete application graph | A selected delivery/job export needs a reviewed dependency-closure selection contract, not row filters applied after export |
| Existing business rows | `plan_records()` blocks application import if any business resource is occupied | Present empty-target behavior is intentional; changing it requires changes to planning, apply, verification and recovery together |
| Account mapping | Explicit source-key to target-PK mapping; distinct source accounts cannot map to one target; application mappings preserve exact usernames | Username/email equality is a suggestion for the operator, not sufficient evidence to grant an incoming identity ownership of an existing account |
| Target review digest | `_target_fingerprint()` includes account values and business **counts**, plus destination/schema/contract identity | Counts cannot detect an edited existing release, changed delivery owner or changed review decision when row counts stay equal |
| Apply | `apply_records()` validates again, inserts business rows with original PKs, maps only user FKs and preserves timestamps using raw inserts | Every resource needs an explicit planned identity map; arbitrary `update_or_create()` would bypass the intended no-overwrite contract |
| Verification | `verify_records()` compares the complete actual business tables against the imported graph | Must become subset reconciliation with recorded created/reused identities and evidence that pre-existing rows stayed unchanged |
| SQL/files recovery | [`service.run_operation()`](../../src/qc_tool/database/transfers/service.py) publishes owned immutable files, then inserts records and one `TransferReceipt` in a SQL transaction | Retain this single orchestration path; do not create a UI-only import path with weaker crash handling |
| Repeat imports | [`TransferReceipt`](../../src/qc_tool/database/models.py) has unique package and operation UUIDs | Same-package retry can recover an uncertain commit; a new package UUID still needs stable record identities to detect records imported before |
| Schema drift | [`schema_fingerprint()`](../../src/qc_tool/database/transfers/contracts.py) binds portable input to exact current model/validation source and timezone policy | Current drift handling fails closed; an application version label alone is not compatibility evidence |

The audited source locations are functions and model definitions rather than
frozen line numbers because the working tree is under active development.

## Resource identity and dependency inventory

“Candidate match” below means a useful lookup for review. It does not authorize
silent reuse. Except where a narrower reviewed semantic contract explicitly
allows otherwise, reuse must compare every imported field after dependency
identity translation, including timestamps, provenance and null/blank values.
Imported actor/token *snapshot* fields retain source values; they are not live
credential foreign keys.

| Portable resource / model / SQL table | Primary identity | Enforced alternate uniqueness | Dependencies and identity-bearing values | Safe candidate match and special restrictions |
| --- | --- | --- | --- | --- |
| `accounts` / Django `User` / `auth_user` | Package-local positive source account key; target integer PK allocated or explicitly mapped | Exact username is SQL unique; importer also detects case-insensitive username collisions | Product grants and group names are proposals, not authority; `date_joined`, profile fields retained for created account | Explicit target mapping; never auto-map by numeric PK, email or name. New portable accounts are inactive, have unusable passwords, no staff/superuser flags and no imported grants. Application upload paths currently require exact username preservation |
| `products` / `Product` / `catalog_product` | Integer PK | `ident` unique | `ready_by_id` → account; readiness revision, readiness timestamp, username snapshot and scope digest | `ident` finds a candidate. Existing operational state and readiness evidence must stay unchanged. A new scope cannot inherit an old product's readiness confirmation merely because its identifier matches |
| `definitions` / `QcDefinition` / `catalog_definition_revision` | Integer PK | `(product_ident, digest)` unique | `product_ident` is a canonical logical identifier, not an SQL product FK; original specification SHA-256, JSON document, original source path/import time | Match canonical product identifier plus original-byte digest, then compare remaining definition content. Original bytes must exist and validate. JSON serialization is not a replacement for the original specification |
| `releases` / `ProductRelease` / `catalog_release_revision` | Integer PK | `(release_key, revision)` unique; one `is_current=True` row per `release_key`; `supersedes_id` is one-to-one | `product_id` → product; `supersedes_id` → earlier release in same product/stream; `approved_by_id` → account; catalog digest, approval, coverage and source evidence | Match release key/revision only after checking mapped product and complete immutable content. A second current release or second successor is a business conflict; never clear an incumbent's current flag automatically |
| `release_definitions` / `ProductReleaseDefinition` / `catalog_release_definition` | Integer PK | `(product_release_id, qc_definition_id)` unique; one primary definition per release | Release and definition FKs; `is_primary` | Match the translated release/definition pair and same primary flag. Do not silently replace a primary definition |
| `units` / `ProductUnit` / `catalog_product_unit` | Integer PK | `(product_release_id, product_unit_code)` unique | Release FK; canonical unit code; source value, provenance, creation time | Match translated release plus code and compare the full immutable unit. Unit PK can also be embedded in published manifest evidence |
| `remote_sources` / `S3Info` / `storage_delivery_source` | Integer PK | No alternate SQL uniqueness | Host, bucket and prefix; `credential_ref` deliberately excluded from portable records | Endpoint/bucket/prefix are only a candidate tuple and may be duplicated. Imported history gets blank credentials. Never reuse or expose a target credential merely because incoming coordinates match |
| `deliveries` / `Delivery` / `execution_delivery` | Integer PK | No alternate SQL uniqueness | `user_id` → owner; `s3_id` → remote source; filename, size, uploaded/submitted times, deletion state, product/unit projections, content checksum | Local storage address is owner username plus filename. Require exact byte size/SHA-256, explicit owner identity and full retained metadata before reuse. Same filename, same numeric PK or same size alone is insufficient. Delivery PK appears in published manifests |
| `jobs` / `Job` / `execution_job` | UUID PK | UUID uniqueness | Delivery FK; optional release/definition FKs; optional requesting-user FK; requester username and API-token ID/name snapshots; input SHA-256; period and QC parameters | UUID is stable and must not be regenerated for a collision. Same UUID with different payload is a conflict. Only terminal supported job states are transferable. Work artifacts live under `work/job_<uuid-without-hyphens>`. `worker_url` is excluded and imported as null |
| `submissions` / `DeliverySubmission` / `publication_submission` | UUID PK | One-to-one delivery and job; at most one published/accepted submission per unit | Delivery/job/release/unit FKs; optional submitting-user FK; submitter and API-token snapshots; publication digest/key/input hash; review state/version and receipt times | UUID remains stable. Complete immutable publication receipt and original artifact tree must agree. A second accepted candidate for an existing unit requires an explicit domain decision; it cannot be inserted with the incoming accepted flag without checking the incumbent |
| `conflicts` / `SubmissionConflict` / `publication_conflict` | Integer PK | One-to-one product unit | Unit FK; optional selected-submission FK; optional resolving-user FK; selected candidate, state/version, opening/resolution times, resolver snapshot/notes | Match the translated unit only as a candidate. Independent conflict histories may share the same unit but differ in meaning/version. Reuse requires complete matching state/history; do not silently replace the current target decision |
| `conflict_events` / `SubmissionConflictEvent` / `publication_conflict_event` | Integer PK | `(conflict_id, version, event_type)` unique | Conflict FK; optional selected-submission/user FKs; actor username, decision notes and original timestamp | Append-only source event identity includes its source conflict and version/type. Matching version/type alone does not prove identical history. Never renumber events to make two different histories fit |
| `review_events` / `SubmissionReviewEvent` / `publication_review_event` | Integer PK | `(submission_id, version)` unique | Submission FK; optional actor FK; actor username, decision, notes, original time | Append-only source history. Declines require notes. Reuse only a fully matching event; conflicting decision/version cannot be silently overwritten |

Additional identities outside the portable application graph:

| Resource | Current treatment | Additive-import boundary |
| --- | --- | --- |
| User password hashes, API credentials, sessions, direct permissions and framework rows | Included in full native SQL backup; excluded from portable accounts/application | Do not imply the portable package is a complete credential backup. Optional future credential transfer needs its own reviewed identity/authority contract and explicit choices |
| `UserProductGrant`, groups | Exported as account proposals, not auto-applied | Existing access controls remain the sole way to grant operational access after import |
| `TransferReceipt` | Native backups retain rows as data; portable packages do not replay source receipts | Source history cannot become target execution authority. Current import creates a new local receipt with a locally approved plan |
| Worker bindings, private S3 secrets, environment configuration, external objects | Excluded from portable import | Imported metadata does not prove deployment access to an S3 object or justify reusing a target credential |

## Graph order and exclusion closure

The current `RESOURCE_FIELDS` order is already a useful dependency order:

```text
accounts ───────────────────────────────────────────────────────────────┐
products → releases → release_definitions ← definitions                │
                    → units                                            │
remote_sources → deliveries → jobs → submissions → conflicts → events  │
                               │          └──────────────→ review_events
                               └─ optional release/definition/account FKs
```

Release self-links additionally require increasing revision order. An actual
planner should derive the reviewed FK graph from the explicit registry and
validate its ordering, rather than maintain separate incomplete lists in forms,
JavaScript and SQL insertion code.

Exclusion is a decision about the incoming branch, not deletion of any target
row:

1. A source record has one terminal decision: create, reuse, skip or unresolved.
2. Every included non-null FK must resolve to an included created or reused
   source dependency. An omitted dependency cannot be changed to null just to
   permit insertion, even if SQL allows null.
3. Skipping an incoming parent excludes all incoming descendants that require
   it. For example, skipping a delivery excludes its jobs, submissions,
   submission reviews and any selected-candidate/conflict evidence that cannot
   remain consistent without those submissions.
4. A dependency already proven equivalent to a target record may remain
   reusable even if a different incoming child is excluded. Excluding one job
   must not exclude every other job on its valid delivery.
5. Cross-references require repeated closure until no unresolved dependency
   remains. A conflict whose selected submission is excluded cannot survive
   unchanged as a resolved conflict. The planner should exclude that incoming
   conflict and its events, not invent a new resolution.
6. Artifacts are projected from the final included graph. Excluded incoming
   jobs/publications must not publish their files; pre-existing shared files
   are never deleted. A file needed by another included row remains included.
7. The review page shows explicit choices, the resulting dependency exclusions
   and counts per resource. Changing a choice invalidates the reviewed plan.

Avoid an ambiguous “keep existing” operation. Its safe meaning is either
**reuse this proven equivalent target identity**, or **exclude these incoming
records**. It must never bind different incoming immutable content to an
existing row merely to satisfy a foreign key.

## Exact create/reuse/skip semantics

### Create

- Only insert an included record with fully resolved dependencies and no
  alternate-key, UUID, storage or business-policy collision.
- Preserve stable UUIDs, source timestamps and provenance snapshots.
- Allocate integer destination keys server-side when the reviewed import mode
  supports translation. A source integer PK alone is never an identity match.
- Record each translation in the approved plan and durable import result.
- Never call a save path that schedules QC jobs, republishes a submission,
  updates operational projections or sends messages as a side effect of
  reconstructing history.
- Existing accounts and business rows remain unchanged unless the product
  separately introduces a clearly reviewed, audited domain transition. Such a
  transition is not an incidental merge conflict choice.

### Reuse

- A lookup yields zero, one or multiple candidates. Multiple candidates require
  explicit operator resolution; no arbitrary `.first()` selection.
- Translate all dependency identities first, then compare every supported
  stored field under an explicit reviewed equality contract.
- Distinguish source-local identity, domain natural identity and target PK.
  They are three different things.
- Reuse does not update account profile/password/grants, replace source files,
  change an existing review decision or give a remote source a credential.
- Record exactly which existing row and field digest were reviewed. Recheck
  those rows under the maintenance barrier and transaction before insertion.

### Skip

- Skip excludes incoming data only and expands the dependency closure above.
- Show the operator what will not be imported and retain that decision in the
  receipt. Never report excluded records as successfully imported.
- A package-level idempotence rule must state whether a committed partial
  import consumes that package. The current unique package receipt naturally
  means yes. Reimporting omitted branches should use a newly reviewed derived
  package or an explicit resumable-selection contract, while stable origin
  identities still prevent duplicate already imported rows.

### Unresolved conflict

- Blocks queueing. No files or rows are published while choices are unresolved.
- Identify the resource, useful human name, reason, incoming/existing evidence,
  affected descendants and available safe actions.
- Do not offer “overwrite existing” as a generic escape hatch for immutable
  evidence or operational account authority.

## Published receipt and readiness constraints

### Publication evidence

[`artifacts._verify_receipt()`](../../src/qc_tool/database/transfers/artifacts.py)
validates original manifest bytes against the submission UUID, delivery ID, job
UUID, release ID, unit ID/code, verified code, input hash, request time and
artifact digest. Supported manifest v1/v2 field names differ, but the identity
binding exists in both. The artifact inventory then binds every retained file
by relative path, size and SHA-256.

Therefore general additive import cannot make a colliding published delivery,
release or unit fit by changing only SQL IDs. It also cannot rewrite the
manifest and recompute its digest: that would create different historical
evidence. The same restriction applies to original product specifications and
uploaded snapshots, whose original bytes are protected by project policy.

The current download path
[`submission_inventory()`](../../src/qc_tool/frontend/dashboard/services/submissions/artifacts.py)
checks manifest digest, submission UUID and per-file inventory. It checks fewer
identity fields than transfer export validation. Successful download alone
therefore does **not** prove a rekeyed graph can be exported again safely.
Acceptance tests must include re-export after merge as well as download.

An initial conservative importer can create/reuse records whose manifest-bound
IDs remain consistent and expose incompatible collisions as exclusions. That
is a bounded capability. It must not be advertised as arbitrary published
collision merging.

### Product readiness

[`_evaluate_readiness()`](../../src/qc_tool/frontend/dashboard/services/catalog/readiness.py)
hashes product ID, readiness revision, active state and current release facts,
including release IDs and accepted counts. Rekeying or adding accepted history
can change the scope. Preserve source readiness as provenance; do not silently
set a target product ready or invent a replacement digest. The existing product
manager confirmation workflow is the correct place to confirm the resulting
scope.

If additive import changes an existing product's accepted scope, an explicit
reviewed policy must decide how it invalidates the operational confirmation
without losing source/target audit evidence. That is a domain transition and
must be visible in the plan, not an undocumented importer side effect.

### Review and conflict history

[`DeliverySubmission`](../../src/qc_tool/frontend/dashboard/domain/submissions/delivery_submission.py)
enforces one published/accepted submission per product unit. Its publication
identity is immutable; only review state/version may change after publication.
`SubmissionConflict` is one current decision per unit, and its events carry
versions bounded by that retained conflict version. Review events are likewise
versioned and append-only.

Two databases can each contain an accepted submission and valid review history
for the same logical unit. Both cannot simply be imported with their accepted
state intact. Likewise, two independent `conflict v1` events cannot be relabeled
as consecutive target events without changing their meaning.

Reuse the existing
[`resolve_submission_conflict()`](../../src/qc_tool/frontend/dashboard/services/submissions/conflicts/resolution.py)
workflow for a **new target-domain decision**, with its actor, version check and
reason requirements. Retain incoming historical decisions as original provenance.
Any mode that changes incoming operational review state needs a versioned,
audited policy, explicit operator review and a retained original source record.
Until that policy exists, conflict must block or exclude the incoming connected
history; do not claim that arbitrary independent histories can already merge.

## Durable, versioned provenance ledger proposal

General merge needs a distinction between an immutable source identity and its
current local representation. A ledger is the appropriate seam; rewriting
source documents to hide target key differences is not.

This section is a design proposal, not implemented behavior.

### Proposed identity layers

| Identity | Proposed meaning | Lifecycle |
| --- | --- | --- |
| Package UUID | One immutable archive and reviewed import attempt scope | A new export gets a new package UUID. Existing package UUID plus different bytes is rejected |
| Source namespace UUID | Stable identity authority for records originating in one source installation/history | Persist across restarts and exports. Never derive it from hostname, database name, username or a secret. Cloning/divergence policy must be explicit |
| Resource + source record key | Record's identity within that source namespace | Stable across exports and target rekeying. It does not become a target FK automatically |
| Source revision digest | Digest of the exact original record and its source dependency identities | A changed source record is a new observed revision requiring review; it does not authorize replacement of an existing target row |
| Target model + PK | Current local database representation | Bound only by a locally approved plan and atomic commit; checked for continued existence/integrity before reuse |
| Imported evidence identity | Original manifest/record IDs, artifact digest and immutable original record bytes/digest | Retained unchanged across merge, export and reimport |

A persistent source namespace is not authentication. An uploaded file can claim
a namespace, so import remains restricted to trusted administrator-supplied
packages. Existing source identity with contradictory content is a visible
conflict, never permission to overwrite.

The namespace must have a documented backup/restore lifecycle. A private shared
deployment state file is possible for an initial bounded design, but a lost or
duplicated file must not silently mint a replacement and make all old rows look
new. A native database clone that retains an old namespace and later diverges
needs conflict detection rather than assuming the two copies are one mutable
authority. If namespace identity is stored outside SQL, its backup must accompany
native SQL recovery.

### Receipt-backed bounded implementation without a schema change

The existing `TransferReceipt.summary` JSON field can hold a strictly validated,
versioned local ledger block in the same transaction as the merge:

```json
{
  "summary_version": 2,
  "mode": "additive",
  "source_namespace": "<uuid>",
  "source_package_id": "<uuid>",
  "created_counts": {"deliveries": 1, "jobs": 1},
  "reused_counts": {"products": 1},
  "excluded_counts": {"submissions": 1},
  "identities": {
    "deliveries": {
      "17": {
        "action": "create",
        "target_key": 42,
        "source_digest": "<sha256>",
        "target_digest": "<sha256>"
      }
    }
  },
  "source_evidence": {"submissions": {}},
  "policy_revision": "<reviewed merge policy>"
}
```

The illustrated shape is an architectural example, not a final reader contract.
Real validation must use resource-specific key types, exact allowed fields,
bounded record counts and no raw credentials. A target digest must be calculated
from the actual translated target content, not merely copied from untrusted
input. Preserve the original source record/evidence or a protected archived
reference when the target representation differs.

Advantages:

- No current schema addition or in-place schema adoption.
- Atomic identity evidence and data insertion using the existing receipt.
- Existing private journal, maintenance pin, package staging and recovery can be
  reused rather than duplicated.
- Stable origin identity can detect duplicates even across different package
  UUIDs.

Limits requiring explicit bounds:

- JSON receipt summaries have no declared unique index on
  `(namespace, resource, source_key)` and no FK from each mapping to its target.
- Repeated history scans can become expensive for hundreds of users and long
  job histories. The database transfer lock must serialize supported writers;
  JSON scans are not a substitute for SQL uniqueness against unrelated writers.
- Deleted/changed targets can leave stale mappings. Revalidate actual target
  rows and their current domain state before reuse; never recreate a missing
  row blindly from a historical mapping.
- Old summaries must keep their own readable version. Recovery must not infer a
  version or silently drop unknown fields.
- A new package must not replay source receipt rows as target authority. The
  local receipt owns the approved mapping; imported provenance is evidence.
- The portable format must carry the full required provenance on re-export.
  A mapping that exists only in a local receipt and disappears during export
  does not solve interoperability.

### Long-term typed/indexed model option

A dedicated origin/representation model could supply unique indexes on source
namespace/resource/key/revision, explicit operation references, indexed target
lookups and more efficient validation. Its advantages increase with record
volume, repeated partial transfers and bidirectional interchange. It also adds
schema, lifecycle and retention responsibilities; a polymorphic target pointer
does not automatically provide SQL referential integrity.

Under the current [draft models-only policy](../../src/qc_tool/database/README.md),
adding such a model would require a freshly initialized disposable database for
development/testing and an explicit reviewed deployment decision. It must not
be added in place to the existing installation, shipped as a baseline or hidden
inside this feature. A later migration-managed release needs its separately
reviewed initialization/adoption transition. The receipt-backed option is a
bounded starting point, not a reason to prebuild future migration machinery.

## Re-export and portable v2 requirements

A future package version should describe original source identities and target
representations separately. Re-exporting an imported record must retain its
original namespace/key and immutable evidence rather than assigning the exporter
as a new origin and turning the same job into a duplicate on return.

For a published submission whose SQL parents have been rekeyed, a versioned
reader must validate both edges:

1. Original manifest IDs/digest → exact retained source submission and source
   dependency identities.
2. Approved local ledger mappings → actual target submission, mapped parent
   records and unchanged artifact bytes.

Every relevant reader must use that reviewed interpretation: merge planning,
postcommit verification, re-export, activation readiness and future recovery.
Do not weaken manifest checks by ignoring delivery/release/unit mismatches
globally. Current package v1 remains strict; unknown v2 fields must not be
silently accepted as v1. Package-version compatibility is distinct from database
schema compatibility.

Source artifacts stay byte-for-byte intact. The interchange representation may
contain a separate normalized target record and provenance block; it may not
replace an original manifest/specification with an edited copy while retaining
its historical identity.

This is the necessary design work for fully general published collision merging.
It is not complete merely because a download route happens to open a ZIP after
SQL insertion.

## Delivery ZIP access: concrete acceptance conditions

An imported historical job must continue to identify its correct original input,
including on a deployment where ZIPs existed before any SQL records were added.
No row should gain access to an unrelated file just because a matching filename
is present.

| Situation | Required behavior |
| --- | --- |
| Canonical owner/filename path exists with exact expected SHA-256 and size | Reuse bytes without overwriting; do not claim ownership of the file for rollback |
| Canonical path absent and verified ZIP is in the package | Publish through the existing exclusive-create artifact journal, then link the imported delivery/job graph |
| Canonical path contains different bytes | Block with the specific delivery/path and safe exclusion choice; never overwrite |
| Same filename exists under another user's directory | Do not auto-link. Ownership/account mapping must be explicit and satisfy the storage contract |
| Several possible old ZIPs match the filename | Do not guess by date, order or size alone. Require a bounded trusted candidate-selection workflow with exact hash validation |
| Delivery checksum missing in historical SQL | A package artifact inventory may supply authenticated-by-review exact expected bytes; preserve original metadata separately. A row-only import cannot establish identity from size alone |
| ZIP missing but original publication contains a valid retained input copy | A future reviewed resolver may use that specific submission inventory as evidence; it must not silently accept an arbitrary file search result |
| Deleted local delivery has no retained upload | Preserve the historical deletion state and present unavailable download clearly; do not claim a ZIP was restored |
| Remote delivery | Keep remote availability/credential provisioning explicit; SQL import is not proof of S3 access |

Tests must request the historical job's actual authenticated download route as
its permitted owner/administrator, compare downloaded bytes/digest, and prove an
unrelated user cannot access it. Then re-export the imported graph and verify
the publication/ZIP inventory again. Include old non-latest jobs: using only the
delivery's latest job can conceal a broken historical relationship.

## Implementation and verification sequence

1. Introduce one central immutable merge-plan contract with explicit identities,
   decisions, dependency closure, storage projection and a human-readable
   conflict list. Keep native recovery separate in the UI.
2. Implement a bounded create/exact-reuse/exclude mode whose evidence remains
   valid without published-ID rewriting. Name and document unsupported
   collisions rather than treating them as successful merges.
3. Bind the plan to target row values, package bytes, existing file hashes,
   identity mappings, active database and maintenance generation. Recompute
   immediately before enqueueing and inside the coordinated execution path.
4. Store created/reused/excluded mappings in the atomic receipt. Reconcile only
   the affected subset and prove pre-existing rows/files were unchanged.
5. Reuse existing UI patterns: paginated identity mapping, summary counts,
   expandable technical evidence, saved choices and a separate final review.
   Domain review conflicts should lead to the existing review/conflict pages
   when their required provenance policy is defined.
6. Design and validate portable provenance v2 before claiming arbitrary
   published-collision merging or reliable round trips between independently
   populated installations.

Meaningful tests need populated source and populated destination fixtures with
integer PK collisions, exact and contradictory natural keys, different account
PKs, terminal UUID jobs, pre-existing correct/wrong ZIPs, immutable published
trees, accepted-unit conflicts and append-only events. Verify no changes on
unresolved conflict; no writes to pre-existing rows; stale-review rejection
after a same-count target edit; same-package crash recovery; cross-package
stable-origin reuse; explicit excluded-branch retry semantics; SQL failure file
rollback; lost commit acknowledgement; unauthorized download denial; and
merge → re-export → reimport without duplicate jobs or modified manifests.

Both SQLite and disposable PostgreSQL tests are needed. Native dumps are not
evidence that a portable graph merge is correct. Existing serving/original
databases and their stored ZIPs must remain untouched during this research and
implementation verification.
