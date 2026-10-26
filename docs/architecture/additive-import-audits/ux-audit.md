---
title: Additive import UX audit
nav_exclude: true
search_exclude: true
---

# Additive record transfer: Admin UX audit and implementation contract

> Historical research, 21 October 2026. This appendix records the pre-change
> implementation and proposals considered then. It does not describe current
> behavior. See [Additive record imports](../additive-record-import.md) for the
> implemented design and its limits.

Status: researched proposal, not implemented. Reviewed against the working tree on 21 October 2026. The current full database restore remains a separate recovery operation.

## User goal and safe intent

An administrator needs to add users, deliveries, QC jobs and their connected history to the current installation without replacing existing records. They must be able to resolve identity collisions through Admin and open an imported job to download its original delivery ZIP, including when that ZIP was already retained on the destination server before the import.

The primary task should therefore be labelled **Import records into this installation**. Its one-sentence promise is: “Add new records, review matching records, and keep existing information unchanged.” Full database restoration belongs under **Restore a full database backup** with the existing separate-database review, switch and rollback flow. A native PostgreSQL archive must not silently take the additive route: it contains executable SQL and has different compatibility, permissions and file requirements.

## What exists today

| Area | Observed behavior | Consequence for additive import |
| --- | --- | --- |
| Admin home | Sparse task cards, direct Export / Import actions, state badge and a collapsed advanced directory in `templates/admin/qc_tool_index.html` | Reuse its task-led language and layout; do not add a second dashboard or simulated database controls. |
| Transfer page | Export / Import / Recent transfers tabs; native form controls; count tables; maintenance status; collapsible technical details | Extend these components instead of introducing a separate frontend framework. |
| Identity review | `AccountMappingForm` and a 20-row server-paginated table explicitly create inactive users or map existing users | Retain this review; expose its implications for ownership, credentials and access. |
| Review protection | Plan hash, maintenance generation, destination confirmation, revalidation and asynchronous operation polling | Bind every conflict decision and file decision to the same server-reviewed plan. |
| Application planning | `records.plan_records()` rejects any occupied QC business table | This is a backend restriction, not a wording defect. Remove it only with a dependency-aware additive planner and apply implementation. |
| Application application | `apply_records()` inserts original business PKs and validates the incoming graph; `verify_records()` compares whole destination tables | Additive import requires identity translation and scoped verification of imported/reused records; changing the page alone is insufficient. |
| ZIP download | `views/deliveries/files.py` resolves the delivery owner's username plus `Delivery.filename`, then opens a regular artifact under the configured media root | Ownership/path compatibility and verified bytes are prerequisites for a functioning imported download. |
| Job result | `templates/dashboard/jobs/result.html` links to `download_delivery_file(delivery.id)` and exposes job UUID, specification digest and delivery digest | Preserve these routes and establish the correct imported job → delivery → owner graph. |
| Product conflict review | Submission pages compare candidates and require explicit, version-checked decisions | Reuse the visual comparison and stale-decision protection. Do not call the submission replacement service for import collisions: it can reject existing competing submissions. |

## Four-step import workflow

### 1. Upload and identify the package

The Import tab presents **Add records** as the normal task and **Restore full backup** as a distinct recovery task. Upload validates the package before any destination business write. Display the source version, export time, scope and counts. The administrator can upload before maintenance, then follow the existing return link through maintenance readiness.

Use a short scope card rather than a long introduction: “Users, products, deliveries and QC history. Existing records stay unchanged.” A portable package's credential/access exclusions must remain visible. Do not imply that the portable profile is a complete PostgreSQL backup.

For a native package uploaded to Add records, explain the mismatch and offer the existing recovery workflow. A future native-to-portable extraction workflow would need its own reviewed design; no SQL should be executed against the serving database as a shortcut.

### 2. Review what will be added and whether files are available

Show one compact resource table with **New**, **Already present**, **Skipped** and **Needs a decision** columns. Below it, show two focused sections: **Resolve identities** and **Delivery files**. Hide technical hashes and package internals in the existing disclosure panel.

Use explicit dispositions:

| Disposition | Meaning | Default |
| --- | --- | --- |
| Add new | Insert a new destination identity and translate its connected references | Only when the planner proves this is a distinct valid record. |
| Reuse existing | Point imported records to a verified compatible destination identity; do not update it | Identical verified records may be proposed automatically, with the evidence shown. Explicit confirmation remains necessary for ownership/account matches. |
| Skip incoming | Exclude the incoming record and its required dependent subgraph, while retaining existing records | Available only when the planner can calculate a valid remaining graph. |
| Needs a decision | Identity is ambiguous, fields differ, or dependency/file evidence is incomplete | Blocks confirmation until resolved or the affected incoming subgraph is skipped. |

Counts must distinguish account profiles from roles/access. Mapping an existing account must not replace its password, contact profile, permissions or grants. Newly created portable accounts remain inactive until the established access workflow activates them.

### 3. Resolve conflicts and revalidate

Use a paginated native form table, consistent with account mapping. Each conflict contains a human label, identity evidence and a concise field comparison: **Existing value** versus **Incoming value**. Show only differing non-secret fields by default, with full identity details in a disclosure. Avoid dumping raw JSON.

Each row offers only choices permitted by the planner. Do not offer generic “overwrite,” “take newest” or table-wide blind merge controls. For catalog/release/specification identities, equality and compatibility rules belong to the domain planner; an administrator should not bypass invariant checks with a dropdown.

For **Skip incoming**, display the calculated impact before saving: for example, “Skip this delivery and its 3 jobs, 1 submission and 2 review events.” Recompute the dependency closure after every saved choice. A resource referenced by a retained incoming record cannot be skipped independently. A conflicting product/unit history may require skipping a larger connected group; tell the administrator exactly what is excluded.

Keep separate paginators for account mapping and record conflicts. **Save choices and validate**, **Save and next**, and **Save and previous** preserve already reviewed choices on other pages. Unsaved choices disable **Import records**, with the existing inline dirty-state notification. Server validation remains authoritative when JavaScript is unavailable or bypassed.

After revalidation, show the new summary and any unresolved dependencies. The final confirmation names the active database, repeats additions/reused/skipped counts, and requires “I reviewed the changes and verified the delivery files.” The plan hash must include all decisions, identity mappings, target evidence, included subgraph and file evidence. A changed target or file requires a fresh review.

### 4. Import and verify the usable result

Reuse the durable asynchronous operation screen and Recent transfers. Progress should describe meaningful stages: **Checking reviewed plan**, **Preparing verified files**, **Adding records**, **Verifying links and downloads**. These are actual runner phases, not client-side timers.

Completion shows created/reused/skipped counts and an **Imported deliveries and jobs** table with **View job** and **Download original ZIP** links. Generate links from destination identities returned by the committed receipt, not the package's old numeric PKs. Reuse `show_result` and `download_delivery_file` and their existing authorization. Paginate large results rather than rendering all history on one page.

An uncertain commit stays in the existing recovery state. Recovery must reconcile the saved identity map, receipt and retained file evidence; it must not insert the same records again. Maintenance remains on until verification/recovery is complete. Do not describe an additive import as switchable or automatically reversible: native database switch/rollback is a different operation.

## Retained ZIP verification is part of the review

The destination may contain uploads before any business rows are imported. File existence or a matching basename is not proof that an imported delivery references the correct ZIP.

| File state shown to administrator | Required server evidence | Allowed action |
| --- | --- | --- |
| Included in package | Expected regular file, size and SHA-256 match verified package inventory | Publish without replacing destination files, or reuse an identical destination file. |
| Already on server — verified | Configured storage resolver yields an allowed regular file; expected size/SHA-256 match package or trusted job input evidence; owner and filename identity are compatible | Explicitly reuse the retained file. Show this disposition in the final review. |
| Missing | Neither package bytes nor a verified configured destination file are available | Block the non-deleted delivery/history, or skip its incoming dependent subgraph. |
| Different file | Allowed destination path exists but bytes differ | Block. Preserve the existing file. Offer skipping the incoming subgraph; a future controlled relocation workflow would need explicit identity/path rewriting and review. |
| Historical file intentionally absent | Incoming record is explicitly deleted or supported historical optional artifact semantics apply | Preserve the historical state and display a warning; never offer a download that the importer claims was verified. |

Never accept an arbitrary filesystem path from a form, scan unrestricted server directories, follow symlinks, or trust a basename/date/size alone. Show logical storage labels rather than absolute private paths. A same-name retained file with unknown expected content must remain **Unverified**, even if the UI provides a separate administrator-assisted reconciliation workflow later.

Existing application mapping limits owners to matching usernames because upload paths use usernames. Retain that constraint until a reviewed storage-identity design removes the dependency. If username renaming or a different owner is proposed, explain the blocker; do not silently make an existing ZIP unreachable.

Acceptance must prove the complete chain: imported destination job UUID resolves its destination delivery; that delivery passes existing access checks; the real download endpoint streams exactly the expected ZIP bytes. A template link or a successful `Path.exists()` check is insufficient.

## Proposed service and plan contract

Keep policy, identity translation, dependency closure and file evidence in the central database transfer package. The view should continue to orchestrate native forms and service calls, not perform database merges or inspect ZIP bytes.

```python
# Existing service entry points remain the facade; additions are illustrative.
plan_import(operation_id, actor, mappings=None, resolutions=None, file_choices=None)
start_import(operation_id, actor, plan_hash, generation, confirmed_scope)
get_operation(operation_id, actor)  # includes safe summary and paginated result identifiers
list_import_conflicts(operation_id, actor, page=1, status="unresolved", resource=None)
list_import_results(operation_id, actor, page=1)  # destination IDs only, access checked
```

For small plans, the first implementation may render conflicts/results directly from a bounded server journal instead of adding routes. Preserve a stable service representation so pagination does not require redesigning domain logic. Forms submit only server-known row keys plus enumerated choices. A numeric source PK must never be treated as a destination PK without a verified mapping.

```json
{
  "mode": "additive",
  "profile": "application",
  "target_label": "postgresql / current_database",
  "plan_hash": "reviewed-plan-digest",
  "can_apply": false,
  "merge_summary": [
    {"resource": "deliveries", "label": "Deliveries", "create": 12, "reuse": 3, "skip": 1, "blocked": 1}
  ],
  "record_conflicts": [
    {
      "key": "opaque-server-generated-review-key",
      "resource": "deliveries",
      "label": "Delivery example.zip",
      "reason": "The incoming identity matches an existing delivery, but verified content differs.",
      "differences": [{"field": "Delivery SHA-256", "current": "current-digest", "incoming": "incoming-digest"}],
      "choices": [{"value": "skip_subgraph", "label": "Skip incoming delivery and connected history"}],
      "resolution": null,
      "impact": {"deliveries": 1, "jobs": 3, "submissions": 1},
      "blocker": "Choose a safe disposition. Existing records will not be changed."
    }
  ],
  "delivery_files": [
    {
      "key": "opaque-file-review-key",
      "delivery_label": "example.zip",
      "status": "retained_verified",
      "size": 12345,
      "sha256": "expected-digest",
      "job_count": 3,
      "disposition": "reuse_verified"
    }
  ],
  "blockers": ["1 incoming delivery needs a decision."],
  "warnings": [],
  "exclusions": ["Portable account profiles do not include credentials or automatic product access."]
}
```

The public representation omits raw credentials, password hashes, API tokens, connection strings, private staging paths and internal filesystem paths. Persist the exact private identity translation and expected evidence in the operation/receipt; the UI needs only safe labels, differences, allowed decisions and destination IDs.

## Roles, boundaries and accessible interaction

- Keep transfer creation, conflict resolution, apply, package download and retained-file review administrator-only at both the service and HTTP layers. Ordinary Django staff status or product-manager status alone is insufficient. Package content must not grant the importer extra authorization.
- Product managers and end users view resulting jobs/downloads only through existing product and ownership access rules. A successful import must not broaden access or let a package choose a destination owner without explicit validated mapping.
- Keep CSRF, maintenance readiness/generation, no-store responses and the existing maintenance-exempt transfer controls. Exemption authorizes the fenced import workflow; ordinary edit/run/upload controls remain blocked for everyone.
- Render text through normal template escaping. Do not expose full user email addresses unnecessarily outside authorized account review, and never display secrets as field differences.
- Reuse the established Admin cards, tables, notifications, button hierarchy and dark/light theme variables. Use one primary action per step. Put recovery/database-switch details outside the additive flow's main content.
- Use table captions, labelled form fields, `aria-current="step"`, inline error associations and status text that does not depend on colour. Keep horizontal table scrolling on small screens and retain usable save/review actions without JavaScript.

## Concrete change and test matrix

| Existing file / area | Proposed change | Required verification |
| --- | --- | --- |
| `database/transfers/records.py` or extracted central merge module | Plan stable/natural identity matches, translate all PK/FK references, calculate skip closure, insert additions only, verify imported/reused scope rather than all destination rows | Populated target; unrelated numeric PK collisions; exact duplicates; incompatible natural identities; account ownership; event/history invariants; no existing field/approval/credential change; deterministic replan. |
| `database/transfers/service.py` | Persist reviewed choices; include identity/subgraph/file evidence in review hash; pass reviewed plan to runner; return safe completion identities | Stale target/file/choice rejection; unknown choices/keys; concurrent request serialization; idempotent recovery; committed receipt reconciliation; native restore unchanged. |
| `database/transfers/artifacts.py` | Explicit packaged/retained/missing/different evidence and safe reuse through established resolvers | Retained ZIP pre-dates DB installation; checksum mismatch; unknown expected checksum; symlink/traversal/case collision; interrupted publication; no overwrite/removal of reused files. |
| `dashboard/forms/data_transfers.py` | Native conflict-resolution form with server-generated keys/choices, existing account mapping, final scope acknowledgement | Tampered source/target/choice rejection; per-page preservation; invalid data cannot apply; account constraints and no unexpected access grants. |
| `dashboard/views/admin_data_transfer.py` | Orchestrate merge pages and counts, save/revalidate resolutions, paginate evidence/results, generate authorized destination links | Administrator-only GET/POST/status/download; correct PRG/refresh behavior; unsaved choices require review; escaped labels; no private evidence/credentials in rendered responses. |
| `templates/admin/data_transfer.html` and scoped CSS | Four steps, concise resource summary, field differences, subgraph impact, retained ZIP statuses, completion job/download links | Desktop/mobile, light/dark, keyboard and no-JavaScript behavior; blocked confirmation understandable; portable exclusions distinct from full backup fidelity. |
| `static/dashboard/js/admin/data-transfer.js` | Extend dirty-state listener to record/file choices; preserve existing polling | Changed radio/select/checkbox decisions disable apply; canonical GET refresh; no unsafe dynamic HTML or navigation; existing status polling/error behavior stays green. |
| `templates/admin/qc_tool_index.html` | Label the task card for record transfer plus separate backup recovery navigation | Existing role-aware cards remain accurate; direct Add records / Export links; ordinary staff/product managers do not gain controls. |
| Existing `views/deliveries/files.py`, job result view and `jobs/result.html` | Prefer no route changes; verify correct destination relationships and usable original-file links | Real HTTP imported job → delivery download streams expected SHA-256; owner/manager/admin access passes as intended; unrelated user denied; deleted files remain unavailable. |
| `dashboard/tests/test_admin_data_transfer.py`, JavaScript transfer tests and disposable PostgreSQL integration tests | Add merge scenarios alongside native backup/restore regression tests | Successful mixed create/reuse/skip run; blocked conflict path; repeated package/recovery; source databases/files retained; no writes to a developer/production database during tests. |

Release acceptance should include an isolated HTTP rehearsal with a populated disposable target and a pre-existing retained ZIP, not only mocked view tests. Record counts/fingerprints of unrelated destination data before and after, verify the imported job's actual download bytes, and confirm a second attempt cannot duplicate committed records.
