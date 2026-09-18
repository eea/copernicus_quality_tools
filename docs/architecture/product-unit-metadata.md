---
title: Product unit metadata
parent: Architecture
nav_order: 5
---

# Product unit metadata

A delivery ZIP represents one product unit. The catalog defines the units
required by each product release; QC verifies the unit contained in a user's
ZIP. A worker observation never creates a required catalog unit.

## Canonical identifiers

The business field is `product_unit_code`. Shared normalization in
`qc_tool/product_units.py` trims whitespace, folds case, rejects control
characters and limits codes to 255 characters. Codes are otherwise opaque:
`007` and `7`, or `ee001l1` and `ee001l`, can identify different units.

An uploaded specification can declare a top-level `product_units` list. This
list supplies its draft delivery plan without changing the executable checks.
An administrator approves the required units before submissions can contribute
to accepted coverage. See [product definitions](../development/product-definitions.md).

Legacy geographic naming checks still use `parameters.aoi_codes` and capture
aliases such as `fua`, `du` and `delivery_unit_id`. Their worker output may still
contain `aoi_code`. The compatibility adapter applies the historical geographic
normalization only to those legacy inputs. New product-unit identifiers must
not silently lose numeric padding or geographic suffixes. Actual GIS areas of
interest and boundary algorithms continue to use geographic AOI terminology.

## Persistence and trust

| Field | Meaning |
| --- | --- |
| `ProductUnit.product_unit_code` | Immutable required unit in a particular release revision |
| `Job.submitted_product_unit_code` | Identity verified inside the ZIP by this execution |
| `Job.product_unit_code` | This execution's canonical result projection |
| `Delivery.product_unit_code` | Canonical result projection from the deterministically latest job |
| `Delivery.submitted_product_unit_code` | Verified ZIP identity, retained across later failed runs |
| `DeliverySubmission.product_unit` | Exact required unit authorized by the job's snapshotted release |
| Submission `product_unit_code` / `submitted_product_unit_code` | Immutable expected and verified snapshots |

Uploads and new jobs start with unknown unit metadata. The first terminal job
transition freezes status, unit metadata, result document and checksum. A
successful job must identify exactly one unit. A later contradictory result
cannot replace the verified identity of the same delivery.

Ingestion distinguishes an absent or malformed unit (preserve known metadata),
explicit null (clear that job's projection), and a valid identifier (set it).
The delivery projection follows the latest job ordered by creation time and
UUID, so polling an older job cannot overwrite the latest result. Raw worker
result bytes and their checksums are retained unchanged; adapters operate on
projections, not archived artifacts.

Submission requires a successful latest QC run, matching input digest and an
exact match to a required `ProductUnit` in the job's authoritative release.
Publication manifests use version 2 product-unit keys. Version 1 manifests are
verified with their original field names and bytes; they are never rewritten
merely to update terminology.

## Authorization

Product assignments authorize users to submit deliveries, run QC and request
review for their assigned products. Product managers review assigned products.
A unit code from a ZIP is content metadata, not an authorization grant.

Region grants use the separate `UserRegionGrant.region_code` field. Region
access still compares the exact grant with the uploader's profile country;
it does not infer geographical permissions from a product-unit identifier.

## Services and recovery

`frontend/dashboard/services/product_units/` owns result interpretation,
terminal persistence, latest-job projection, secure artifact loading and
resumable backfill. Job serializers expose canonical product-unit keys and
remove raw input aliases from public reports.

```bash
python3 -m qc_tool.frontend.manage backfill_product_unit_metadata --dry-run --limit 100
python3 -m qc_tool.frontend.manage backfill_product_unit_metadata --batch-size 100
```

Backfill reads bounded, contained result artifacts. It does not infer unit
identity from filenames or rewrite immutable submitted records. Missing or
malformed results leave existing metadata intact. Draft schema changes require
a fresh disposable database; this metadata command is not a schema converter.
