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
| `scripts/migration/legacy/` | Offline legacy-source preparation, fresh-target rehearsal and reconciliation |
| `scripts/testing/` | Explicit integration runs that collect QC evidence |
| `scripts/tests/` | Maintained offline tool regression tests, collected in CI |
| `scripts/catalog/` | Manual read-only recipe diagnostics |
| `scripts/data_preparation/boundaries/` | Explicit generation of boundary resources |
| `scripts/one_off/clc2024/` | Historical product preparation and investigation |
| `scripts/obsolete/wiki/` | Old documentation tools and generated artifacts proposed for removal |

Run commands from the repository root with `python3 -m scripts.<package>.<command>`.
In containers, use the repository as the working directory. Application startup
does not run these scripts.

A one-time production cutover still needs maintained conversion/rehearsal tools
and repeatable tests. Product-specific experiments, captured delivery lists and
generated wiki outputs do not belong in automated QC testing. Promote useful
assertions into tests of the owning application contract before retiring an
experimental diagnostic.

Use the [testing guide](testing.md) for suite commands and the
[database runbook](../../src/qc_tool/database/MIGRATIONS.md) for persistence
operations. The script reorganization changes neither QC algorithms nor product
specification bytes.
