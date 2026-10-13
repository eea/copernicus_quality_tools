---
title: Legacy QC parity
parent: Development
nav_order: 8
---

# Legacy QC parity

[`scripts/testing/legacy_qc.py`](../../scripts/testing/legacy_qc.py)
runs captured production ZIPs through an already isolated current-source worker.
Use `--current-checks` to select every current configured check without
reproducing historical skips. Current configured rules determine the result;
archived acceptance and rejection comparisons provide supplementary diagnostics.
It runs the worker CLI directly; it does not upload or submit
deliveries, contact a frontend, or modify production records or specifications.

## Required production compatibility

For identical delivery bytes, v3.0.0 must preserve production's pass/fail result.
The damaged-ZIP fix is the sole permitted behavior difference. Changes in
validator versions, check severity, recipe selection or geospatial dependencies
are not additional exceptions.

This runner currently collects archived/current diagnostic evidence. Strict
compatibility requires paired production-reference and candidate runs using the
same original specification bytes and production dependency profile. An archived
report from a different worker version is useful history, but cannot replace
that reference run. A mismatch or missing reference evidence prevents a claim
that production compatibility has been verified. The offline tool tests validate
the harness contracts; they do not perform this integration comparison.

## Evidence contract

An accepted result counts only when every configured check appears in the
expected order, every check reports `ok`, no check is skipped, the worker hash
matches, the original recipe bytes are preserved, and the PDF report exists.
A nonpassing control needs a real QC decision. Timeouts, missing boundaries or
masks, INSPIRE service/system failures, lost workers and engine errors do not
prove rejection and are classified as inconclusive. A genuine rejection can stop
the worker before later checks; it does not establish that every check completed.

The result blueprint can contain a record for a check that never ran. Read
`configured_step_entry_count` separately from `executed_step_count`: the latter
counts terminal step statuses, excluding null placeholders and skipped checks.
`all_configured_steps_completed` also requires the configured identifiers in
order and terminal statuses for every entry. Earlier runner reports counted
blueprint entries instead, so inspect their raw step statuses before claiming
completion. An `aborted` result does not establish that the data passed that check.

An archived comparison additionally needs the exact archived job report, the
unchanged input ZIP and its matching historical SHA256. Missing reports, null
historical hashes or different bytes make that comparison **inconclusive**.
They do not prevent current-checks execution or a current passing result.
`step_status_deltas` records differences between archived and current steps.

A historical `ok` also reflects its worker version's check severity.
For example, raster gaps were informational in worker `1.8.4` and became
failures in `2.4.9`. Identical input and identical detected gaps can therefore
change the verdict before any current-source change. Record this as a historical
version mismatch; a production-original recipe alone cannot guarantee old
behavior. This explains the diagnostic difference; it does not waive the strict
production compatibility requirement or prove a v3 regression. Preserve the
recorded historical result and obtain the matching production-reference profile
before drawing either conclusion.

Keep `src/qc_tool/raster` and `src/qc_tool/vector` unchanged during this
verification. Preserve masks, specifications and check severity; record findings
without modifying checks to obtain a passing comparison. Fixes outside those
folders require their own review and fresh evidence. Source changes or restored
files invalidate earlier validation of the resulting checkout: retain earlier
reports as diagnostics, then rerun before making a claim about the new bytes.

Current-checks mode enforces this boundary: protected files must match their Git
`HEAD` bytes, with no additional files in those folders except generated
`__pycache__` content. It records that fingerprint and checks protected bytes,
the wider source fingerprint and imported worker module origins before each
case. Source changes during a case invalidate its evidence and stop the batch.

Keep input/report captures and source credentials in private evidence storage.
Native S3 deliveries can use a combined hash of downloaded files rather than a
ZIP hash. Wrapping the same files in a new ZIP does not make that ZIP comparable
to the historical S3 hash. Inspect the historical hash scope: older download
helpers could replace the primary input hash while downloading MMU neighbours.
A matching neighbour hash does not prove the original primary input's identity.
Missing S3 prefixes and neighbouring-tile dependencies remain coverage gaps;
this runner selects uploaded ZIPs only.

## Runtime and preparation

Prepare the evidence tree and a disposable worker with its own PostGIS storage
and validator dependencies. This script does not create the runtime:

```text
private-evidence/
  candidate-matrix.json
  negative-control-matrix.json
  legacy-reports/<historical-job-uuid>.json
  incoming/legacy-probe/<original-delivery>.zip
  incoming/legacy-negative/<original-negative-delivery>.zip
  production-specifications/<product-ident>.json
  boundaries/
  runtime/
  work/
  reports/
```

Preflight requires the checkout, incoming files, boundaries and selected
specification directory to be mounted read-only. The only writable evidence
mount is `/verification/work`. The worker must publish no service ports and use
`QC_TOOL_VERIFICATION_RUNTIME=yes`, `SKIP_INSPIRE_CHECK=no`,
`USE_LIGHTWEIGHT_VALIDATOR=no`, `INCOMING_DIR=/verification/incoming`,
`WORK_DIR=/verification/work`, `BOUNDARY_DIR=/verification/boundaries` and
`PRODUCT_DIRS=/verification/specifications`. The primary production-original
mount remains required. A repository-default comparison can select the trusted
read-only checkout's `product_definitions` through a per-job `PRODUCT_DIRS`
override. Work storage must contain no uploaded specification overrides.

## Run the available cases

Run from the repository root. Substitute the private evidence directory and
the existing isolated container name:

```bash
EVIDENCE_ROOT="/absolute/path/to/private-evidence"
QC_CONTAINER="qc-tool-legacy-verification"

python3 -m scripts.testing.legacy_qc \
  --evidence-root "$EVIDENCE_ROOT" \
  --container "$QC_CONTAINER" \
  --current-checks \
  --specification-dir "$EVIDENCE_ROOT/production-specifications"

python3 -m scripts.testing.legacy_qc \
  --evidence-root "$EVIDENCE_ROOT" \
  --container "$QC_CONTAINER" \
  --current-checks \
  --username legacy-negative \
  --specification-dir "$EVIDENCE_ROOT/production-specifications" \
  --matrix "$EVIDENCE_ROOT/negative-control-matrix.json"
```

The default matrix is `candidate-matrix.json`; the default input subdirectory
is `incoming/legacy-probe`; stage negative controls separately in
`incoming/legacy-negative`. The runner chooses the first staged uploaded-ZIP
candidate per product, ordered by explicit priority, historical runtime and
archive size. Absent inputs are not tested, so a successful batch is not a
complete catalog coverage statement.

Read `current_check_outcome` independently of `parity_outcome`. Current outcomes
are `passed`, `failed`, `partial` or `inconclusive`; archived parity can match,
differ or remain inconclusive. A valid failed negative control is useful
rejection evidence, even though the current-checks batch returns exit `1` because
that input does not pass all checks. Historical acceptance does not override a
current failure, and missing historical identity does not invalidate an otherwise
complete current check result.

Use `--product` to select one canonical identifier. `--exclude-product` can be
repeated to defer products while keeping their coverage pending; repeat
`--include-product` to restrict a retry cohort. For an explicit original ZIP,
supply `--product` and `--filename`; add `--legacy-report` for the archived
comparison. Optional `--expected-status` checks an available archived status
without overriding it.
`--username` changes the staging subdirectory, and `--repo` selects the checkout.
See `python3 -m scripts.testing.legacy_qc --help` for the current CLI.

For an initial smoke batch, `--max-legacy-runtime-seconds 600` defers cases with
unknown historical runtime or runtime at or above that bound. Repeat
`--priority-delivery-id` to prioritize known deliveries within the selected
batch. These limits and exclusions leave coverage pending; they do not establish
parity for every product.

Disk preflight uses declared uncompressed archive bytes, with defaults of
`--scratch-factor 2.5` and `--reserve-gib 2`, and checks both host scratch and the
worker PostGIS filesystem. Compressed download size alone is insufficient.
`--timeout-seconds` defaults to 90000. Do not reduce disk reserves or skip checks
to turn an incomplete run into passing evidence.

## Archived replay mode

Omit `--current-checks` only when replaying an archived decision. This mode
requires a matching historical input hash before running and reproduces skipped
checks from that exact report. A historical `partial` result is not evidence
that the input would fail the complete current recipe. Prefer historical
`failed` controls without skipped checks for comparisons of genuine rejection.

In replay mode, matched acceptance or matched nonacceptance determines batch
success. This differs from current-checks mode, which requires every selected
input to pass all configured checks for a successful batch exit. Replay does not
enforce the protected-folder `HEAD` guard, so keep those folders unchanged and
inspect the recorded source fingerprint separately.

## Specification and release scope

Specifications and uploaded snapshots remain immutable. The default recipe
directory is the checkout's `product_definitions`; choose captured production
originals explicitly when testing legacy configuration parity. The worker's
primary production-original mount stays in place during a repository-default
comparison.

The captured production `clc2024` recipe differs from the repository recipe:
production additionally permits `eu` and `eea38plusuk`, sets
`gap_width_tolerance=0.02` instead of `0.01`, and supplies
`overlap_width_tolerance=0.01` where the repository recipe omits it. Test the
production-original and repository-default configurations separately and
report their exact recipe hashes. Do not rewrite either specification to make
the comparison pass.

To run the repository-default comparison in the same isolated runtime:

```bash
python3 -m scripts.testing.legacy_qc \
  --evidence-root "$EVIDENCE_ROOT" \
  --container "$QC_CONTAINER" \
  --current-checks \
  --product clc2024 \
  --specification-dir "$PWD/product_definitions"
```

Evidence includes JSON results, PDF reports, console logs, artifact hashes,
recipe hashes, source revision and dirty-tree fingerprint, actual container
configuration and dependency versions. The batch also checks whether source
bytes changed during the run. In current-checks mode, exit `0` means every
selected case has `passes_all_checks=true` and `current_check_outcome=passed`,
the whole selected batch completed and source guards stayed stable. In archived
replay mode, exit `0` instead
requires `parity_matches=true` for every selected case and stable source bytes.
Exit `1` means the applicable batch success conditions were not met; inspect
current outcomes, archived comparisons and any stopped reason separately.
Exit `2` means no ZIP remained in the staged selection; argument errors can also
return `2`.

This evidence applies to those recorded source bytes and runtime settings.
It does not certify complete historical coverage or a packaged v3.0.0 release
artifact. Packaged-image release verification remains a separate requirement.
