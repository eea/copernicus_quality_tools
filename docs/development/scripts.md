---
title: Script organization and lifecycle
parent: Development
nav_order: 9
---

# Script organization and lifecycle

The [maintainer script catalog](../../scripts/README.md) owns the command list,
invocation examples, lifecycle classification and proposed deletions. Scripts
are grouped by purpose:

| Directory | Responsibility |
| --- | --- |
| `scripts/testing/` | Explicit integration runs that collect QC evidence |
| `scripts/tests/` | Maintained offline tool regression tests, collected in CI |
| `scripts/catalog/` | Manual read-only recipe diagnostics |
| `scripts/data_preparation/boundaries/` | Explicit generation of boundary resources |
| `scripts/one_off/clc2024/` | Historical product preparation and investigation |

Run commands from the repository root with `python3 -m scripts.<package>.<command>`.
In containers, use the repository as the working directory. Application startup
does not run these scripts.

Legacy database conversion is performed manually in private operator tooling,
outside the codebase. Prepared database artifacts follow the
[manual restore guide](../../src/qc_tool/database/MANUAL_RESTORE.md).
Product-specific experiments and captured delivery lists do not belong in
automated QC testing. Promote useful
assertions into tests of the owning application contract before retiring an
experimental diagnostic. The documentation site is built from `docs/` with
Jekyll's sitemap plugin; wiki crawlers and generated wiki outputs are not source
assets.

Use the [testing guide](testing.md) for suite commands and the
[database guide](../../src/qc_tool/database/README.md) for persistence
operations. The script reorganization changes neither QC algorithms nor product
specification bytes.
