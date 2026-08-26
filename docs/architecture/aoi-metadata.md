---
title: AOI metadata
parent: Architecture
nav_order: 5
---

# AOI metadata

Every delivery ZIP represents exactly one AOI. QC Tool keeps the AOI observed
inside that ZIP separate from the authoritative AOI expected by a product
release. A failed, incomplete, or ambiguous check remains `null`; a job cannot
finish successfully or authorize submission until it verifies one AOI.

## Why a canonical boundary exists

Product naming contracts use several names for the same concept. They are
accepted only where a QC check reads external metadata:

| External name | Canonical worker-result key |
| --- | --- |
| `aoi_code` | `aoi_code` |
| `delivery_unit_id` | `aoi_code` |
| `fua_code`, `fua` | `aoi_code` |
| `du_id`, `du` | `aoi_code` |
| `code_city`, `codecity` | `aoi_code` |

Alias spelling is case- and separator-insensitive. Workers continue to emit
`aoi_code` for protocol compatibility. In the database it is written to
`Job.aoi_code_submitted`; the legacy `Job.aoi_code` alias is dual-written
during the migration period.
The identifier is trimmed and case-folded. Established Urban Atlas and N2K
suffixes are normalized to their shared FUA or delivery-unit identifier.
Purely numeric identifiers are stored without leading zeroes, so values such
as `007` and `7` cannot become separate indexed records for the same AOI.

## Data flow

```mermaid
flowchart LR
    Names[Product naming capture] --> Core[qc_tool/aoi identifiers]
    Core --> Status[Worker CheckStatus metadata]
    Status --> Result[result.json aoi_code]
    Result --> Ingest[Django AOI result ingestion]
    Ingest --> Job[(Job.aoi_code_submitted)]
    Job --> ZipIdentity[(Delivery.aoi_code_submitted)]
    Catalog[(ProductAOI.aoi_code)] --> Match[Exact release AOI match]
    ZipIdentity --> Match
    Match --> Submission[(DeliverySubmission AOI snapshots)]
    Job --> Legacy[Legacy latest-job aoi_code projection]
    Legacy --> UI[UI, export, delivery API]
    Job --> Reports[History and report API]
```

The implementation is intentionally split into small modules:

```text
qc_tool/aoi/
├── constants.py       stable public key and input aliases
├── identifiers.py     pure normalization and conflict detection
└── metadata.py        job-step metadata merge contract

qc_tool/worker/
├── aoi/
│   ├── metadata.py    worker result adapter
│   └── naming.py      generic raster/vector naming boundary
└── status.py          lightweight QC check result object

frontend/dashboard/services/aoi/
├── artifacts.py       bounded, no-follow result loading
├── contracts.py       typed persistence actions
├── errors.py          stable service exceptions
├── results.py         untrusted result ingestion
├── projections.py     deterministic delivery projection
├── jobs/
│   ├── creation.py   row-locked job creation and provenance
│   ├── completion.py terminal result and one-AOI enforcement
│   └── metadata.py   immutable result metadata and digests
├── lifecycle.py       compatibility facade for job hooks
└── backfill.py        bounded historical artifact backfill
```

## Persistence rules

- Uploading or registering a delivery starts with `aoi_code = null`.
- A new job starts with both AOI fields `null`.
- Waiting and running status updates never read result metadata.
- A terminal status reads the job result and stores a valid canonical value.
- The first terminal transition freezes the Job's status, AOI, result metadata,
  and input checksum; later polling cannot replace historical facts.
- A missing or malformed field preserves the current value.
- An explicit JSON `null` clears the value.
- `Delivery.aoi_code` mirrors the deterministically latest job, ordered by
  creation time and then UUID.
- Creating a newer job therefore resets the delivery projection until the new
  result reports an AOI.
- `Delivery.aoi_code_submitted` is the verified identity of the one ZIP. Once
  populated it is not replaced by a later job. A contradictory later result is
  retained on the Job but changes that job to an error state.
- `ProductAOI.aoi_code` is the immutable expected AOI in a specific catalog
  release. Observed ZIP metadata never creates or changes ProductAOI rows.
- Submission requires an exact match between the successful Job's
  `aoi_code_submitted` and a ProductAOI in the Job's snapshotted release.
- Submission also requires a valid SHA-256 from QC and verifies the local ZIP
  against that immutable checksum before publication.
- `DeliverySubmission.aoi_code` and `aoi_code_submitted` are immutable expected
  and observed snapshots, respectively.
- Deleting the latest job reprojects from the remaining history.
- Conflicting observations produce `null`; the system never chooses one.

Delivery projection changes lock the delivery row first. This is the shared
lock order for creation, status updates, and job deletion, avoiding stale
metadata and reducing deadlock risk during overlapping requests.
Jobs are read-only in Django Admin because direct edits or deletes would bypass
that lifecycle. Use the permission-checked job-history workflow for deletion.

## Security and trust boundary

ZIP-derived AOI remains **content metadata**, not an authorization fact. A name
captured from uploaded content is influenced by the uploader. Region access
continues to use the existing grant/legacy-region policy until every supported
product has an authoritative spatial AOI validation contract.

Do not change region authorization to use either Delivery AOI field merely because
the field is populated. That future change requires:

1. authoritative validation for every AOI-bearing product;
2. explicit semantics for collapsed FUA and delivery-unit suffixes;
3. normalized grant and personal-token snapshot migration;
4. historical-job object-access tests; and
5. a deliberate fail-closed rollout for deliveries whose AOI is unavailable.

This separation lets new aliases be added safely without coupling the shared
identifier package to product definitions or raster/vector implementations.

## Historical jobs

Schema migrations do not read files from shared storage. After deploying the
new columns, an operator may inspect and backfill existing terminal results:

```bash
python3 -m qc_tool.frontend.manage backfill_aoi_metadata --dry-run --limit 100
python3 -m qc_tool.frontend.manage backfill_aoi_metadata --batch-size 100
```

The command is ordered, bounded, idempotent, and ignores unreadable or
ambiguous results. Result documents are opened without following symbolic
links and are capped at 16 MiB before JSON decoding. Run it while the shared
job-result volume is mounted.

The schema migrations also recognize columns created by the former dev AOI
work. They adopt those columns, canonicalize existing Job values in bounded
batches, rebuild every Delivery projection from its deterministic latest Job,
then reconcile the database to the stable `dash_job_aoi_idx` and
`dash_delivery_aoi_idx` index names used by the current models. This also
repairs a partially applied dev schema that had only the Job AOI migration.
