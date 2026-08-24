---
title: Product onboarding
parent: Development
nav_order: 3
---

# Requirements for a new product

Product onboarding is planned work, not only a JSON edit. The request must
provide enough technical, operational, and validation context to implement and
test the workflow safely.

## Lead time

Submit a formal deployment request at least three months before the desired
operational date. This allows product-definition work, missing check
implementation, representative testing, capacity planning, and release
coordination.

## Service and delivery context

Specify:

- EEA-hosted or self-deployed QC Tool instance;
- expected delivery sizes, object counts, and concurrency;
- ZIP upload or S3 registration;
- browser UI, API automation, or both;
- required submission/integration behavior;
- target release and operational dates.

For self-deployment, size frontend storage, worker replicas, PostGIS scratch
space, archive expansion, and validator resources from representative data—not
only compressed delivery size.

## Product technical specification

Provide a Product User Manual or equivalent specification containing:

- file and directory naming;
- versioning rules;
- full layer list, with raster/vector type;
- required and optional attributes;
- CRS/EPSG constraints;
- delivery units and grid/AOI system;
- boundary data when introducing a new grid or AOI;
- required checks and parameters;
- which checks, if any, may be skipped;
- acceptance and expected result criteria.

Select existing checks from the [check catalogue](../checks/index.md). A missing
capability requires an explicit raster/vector implementation task and domain
tests; do not emulate it with an undocumented recipe workaround.

## Test data

Provide at least three representative samples per checked layer, including both
expected-success and deliberately failing cases.

Additional requirements:

- S3 products need least-privilege sample credentials and an approved HTTPS
  endpoint for an isolated test environment;
- parallel tiled workflows need at least `3 × n` samples, where `n` is the
  intended number of parallel workers/runs;
- MMU workflows should include at least one cluster of nine neighboring
  delivery units;
- naming, boundary-edge, empty/nodata, maximum-size, and malformed cases should
  be represented where applicable.

Never commit private sample credentials or restricted production deliveries.

## Implementation separation

Keep the change set reviewable:

1. product-definition recipe and specification mapping;
2. new or changed raster/vector checks, if required;
3. boundary package or AOI integration;
4. representative fixtures and regression tests;
5. deployment capacity/configuration;
6. user/check documentation.

Product definitions and QC algorithms are domain behavior. Do not combine them
with unrelated authentication, infrastructure, or dependency refactors.

## Acceptance checklist

- [ ] Product identifier and description are stable.
- [ ] Every recipe step maps to a documented requirement.
- [ ] Required checks cannot be skipped.
- [ ] Parameters and thresholds have traceable sources.
- [ ] Success and failure fixtures pass expected assertions.
- [ ] Boundary and naming behavior is tested.
- [ ] ZIP and/or S3 intake works within configured limits.
- [ ] JSON, PDF, log, and attachment outputs were reviewed.
- [ ] Expected runtime and storage were measured.
- [ ] UI and API workflows were smoke-tested.
- [ ] Check/user/operator documentation is complete.
