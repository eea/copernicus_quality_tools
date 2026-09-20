---
title: Delivery filename identification
parent: Architecture
nav_order: 8
---

# Delivery filename identification

QC Tool uses parsEO to interpret delivery names and suggest an existing managed
QC specification. The administrator still creates products by uploading reviewed
specification JSON. Parsing never creates products, grants access, verifies ZIP
contents, or completes product units.
Product specification files and uploaded snapshots must never be modified for
identification. Matching rules belong to QC Tool's application configuration.

## Parser and catalog responsibilities

[`delivery_names.py`](../../src/qc_tool/delivery_names.py) is the reusable Python
adapter. It has no Django, database or authorization dependencies. It returns
structured filename observations with a schema family and version, or an
`invalid`/`unsupported` result. It validates basenames, calendar production dates
and chronological survey periods in addition to the upstream schema patterns.
Only an outer `.zip` suffix is removed for parsing; the original name is retained.

Urban Atlas LCU, LCUC, BBH, GUA, STL and the supported legacy DHM convention are
recognized automatically using explicitly selected `0.0.0` schemas. The legacy
PDF subtype is unsupported by parsEO and retains catalog filename matching.
Other packaged families can be enabled through explicit application rules.
The adapter does not use `parse_auto()`, which can select a deprecated matching
schema or report an unrelated family for an invalid filename.

The [catalog resolver](../../src/qc_tool/frontend/dashboard/services/products/identification.py)
maps these observations to current, active, non-retired managed definitions.
Only managed identifiers and descriptions are queried; specification contents
are not read or changed for routing. Filename-based matching remains available for definitions
without explicit rules. Recognized Urban Atlas names require the complete parsed
product identifier (including variable, period and representation/resolution, or
the legacy DHM identity). An arbitrary date or partial family prefix cannot select
a specification. Unsupported legacy names use complete prefix/suffix tokens.
Overlapping matches remain ambiguous rather than choosing the first database row.

| Result | Upload and job behavior |
| --- | --- |
| One matching specification | Check its assignment, associate the uploaded delivery and preselect it for QC |
| Multiple matching specifications | Require access to at least one candidate; store no guessed product; let the user choose an assigned matching specification at QC setup |
| Recognized name, no matching specification | Explain that an administrator must upload or activate the matching specification |
| Invalid supported filename | Explain the naming error before storing upload chunks or creating a job |
| Unsupported legacy name | Preserve existing managed identifier matching and authorized manual QC selection |
| Parser unavailable | Fail explicitly; never downgrade recognition failures into permissive legacy matching |

Candidates are determined independently of user grants. Permissions then filter
the choices and presentation; a grant cannot make a different specification a
better filename match. A recognized but unassigned product cannot fall back to
access to an unrelated product.

Browser preflight, resumable uploads, replacements and local/S3 registration use
the same upload admission service. QC setup restricts the available choices,
and the shared job-creation service repeats the check for both browser and API
requests against the selected immutable specification. Multi-delivery setup
offers only specifications compatible with all recognized names.

## Application matching rules

Configure `DELIVERY_FILENAME_RULES` in the frontend's Django settings. Defaults
live in [delivery_filename_rules.py](../../src/qc_tool/frontend/delivery_filename_rules.py),
separately from `product_definitions/`. Each key identifies an existing managed
specification. For example, an application mapping for `urban_atlas_change` is:

```json
{
  "urban_atlas_change": {
    "family": "copernicus:clms:ua-lcu",
    "schema_version": "0.0.0",
    "match": {
      "variable": "LCUC",
      "survey": "C2021-2024",
      "type": "V",
      "resolution": "010ha"
    }
  }
}
```

This is application configuration and must not be added to a specification. It lets a
specification named `urban_atlas_change.json` match the corresponding Urban Atlas
delivery convention without depending on that arbitrary catalog identifier.
All match fields must equal the parsed values, case-insensitively. Fields and
values are validated against the installed schema. Schema versions are required;
arbitrary filesystem paths, remote schema URLs and executable rules are not
accepted. Explicit rules take precedence over legacy identifier matching, even
when the explicit match fails.

Keep matching fields specific enough to distinguish product variables, periods,
representations, resolutions and variants. Naming schemas do not define the
business product or release. When several managed specifications deliberately
share naming rules, QC setup requires a choice and still applies release and
product-grant checks.

Review routing changes as application configuration changes; restart the frontend
when changing its settings. They introduce no table or schema changes, and do not
alter definition bytes, digests or job snapshots. Existing QC jobs continue using
their original executable definitions. No bundled specification is imported or
activated by installing parsEO or adding an application mapping.

The default application configuration includes rules for the existing UA 2021
`fgb_parquet` and `boundary2018` identifiers because their recipe identifiers
differ from delivery names. Their specification files stay byte-for-byte unchanged;
existing catalog versions work without replacing or re-uploading them.
When the base and variants share the same naming pattern,
they remain separate choices; the filename cannot determine which QC variant is
intended.

## Filename hints and verified units

Upload previews and QC setup show detected product, survey, place and area code
as filename hints. A parser observation such as `BE015L1` does not populate
`Delivery.product_unit_code`, `submitted_product_unit_code` or any job unit field.
The existing worker naming checks verify the archive contents and the submission
workflow matches the verified result to the snapshotted release's required units.

The raw area code is preserved. In particular, the parser does not change
`BE015L1` into the legacy geographic `be015l` or remove zero padding. Any such
translation belongs to the existing specification-specific compatibility
boundary described in [product unit metadata](product-unit-metadata.md).

## Upstream version and verification

The frontend uses the parsEO `develop` commit
[`17725f320c35a270fafcf9dbe03f992a045fd1bc`](https://github.com/copernicus-land/parsEO/tree/17725f320c35a270fafcf9dbe03f992a045fd1bc),
not a moving branch reference. Its source archive SHA-256 is pinned in
[`requirements.frontend.txt`](../../docker/requirements.frontend.txt) and
[`pyproject.toml`](../../pyproject.toml). Runtime parsing is in-process and does
not contact an external service. The worker retains its existing content checks
and does not require parsEO for this integration.

Upstream provisional schemas can change, and parsing alone does not establish
semantic or geospatial validity. Update the source commit and archive hash
together, then run the filename, catalog, permission and registration regressions
before rebuilding the frontend. Use the [testing guide](../development/testing.md)
with disposable databases; do not reset a developer database to install this
application-only change.

Focused suites include `qc_tool.test.test_delivery_names`, dashboard
`test_delivery_identification`, `test_job_setup_identification`,
`test_delivery_upload_check`, local/S3 API registration, and the upload/job setup
JavaScript tests.
