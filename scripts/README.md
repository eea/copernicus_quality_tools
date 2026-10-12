# Maintainer scripts

Choose a command by its purpose and lifecycle. Run commands from the repository
root using `python3 -m scripts.<package>.<command>` so imports and default paths
resolve consistently. Python 3.11 or newer is required for the maintained tools.

Application behavior belongs under `src/qc_tool/`. These scripts provide explicit
operator actions and verification tooling; application startup must not run them.

## Directory map

```text
scripts/
├── catalog/                       # Manual, read-only recipe diagnostics
│   ├── check_tile_codes.py
│   └── naming_examples.py
├── data_preparation/boundaries/    # Explicit generation of boundary resources
│   ├── create_layers.py
│   └── create_masks.py
├── migration/legacy/               # Offline legacy cutover/rehearsal tools
│   ├── prepare_sources.py
│   ├── reconcile_exports.py
│   └── rehearse.py
├── testing/                       # Repeatable QC evidence collection
│   └── legacy_qc.py
├── tests/                         # Offline unit tests for maintained tools
│   ├── migration/
│   └── testing/
├── one_off/clc2024/                # Historical product-specific preparation
│   ├── generate_metadata.py
│   ├── gap_analysis.py
│   └── delivery_list.json
└── obsolete/wiki/                  # Retained removal candidates
    ├── crawl_sitemap.py
    ├── generate_sitemap.py
    ├── sitemap.xml
    └── sidebar.md
```

Keep new production captures, ZIPs, database copies and generated QC reports
outside this catalog. The retained CLC delivery list is a historical exception
pending the removal review below, not a template for new fixtures. Ignored evidence under
`src/qc_tool/database/backups/` remains historical evidence; moving a command does
not rewrite the command paths recorded in those captures.

## Choose the right tool

| Purpose | Command or guide | Lifecycle and effect |
| --- | --- | --- |
| Audit/import a legacy snapshot | [`migration/legacy/rehearse.py`](migration/legacy/rehearse.py) | Maintained cutover tool. Rehearsals are repeatable; each uses a new private output directory and a fresh target. |
| Prepare available mixed history | [`migration/legacy/prepare_sources.py`](migration/legacy/prepare_sources.py) | Maintained cutover helper. Writes a separate interchange and provenance manifest, preserving source bytes. |
| Compare CSV history with XLSX exports | [`migration/legacy/reconcile_exports.py`](migration/legacy/reconcile_exports.py) | Repeatable, read-only verification; prints aggregate differences and fingerprints. |
| Run captured deliveries through an isolated worker | [`testing/legacy_qc.py`](testing/legacy_qc.py) | Repeatable manual integration verification; requires prepared inputs and a disposable worker. |
| Check tooling regressions locally/in CI | [`tests/`](tests/README.md) | Automated offline unit tests; synthetic inputs and temporary directories. |
| Review recipe tile identifiers or naming examples | [`catalog/`](catalog/README.md) | Manual legacy diagnostics; findings require review against current product contracts. |
| Generate boundary resources | [`data_preparation/boundaries/`](data_preparation/boundaries/README.md) | Manual data preparation with explicit sources and output paths; requires GDAL/OGR. |
| Reproduce a historical CLC2024 preparation/investigation | [`one_off/clc2024/`](one_off/clc2024/README.md) | Historical tools retained for review; not automated QC tests. |
| Review outdated documentation tools | [`obsolete/wiki/`](obsolete/wiki/README.md) | Removal candidates; current docs use Jekyll's sitemap plugin. |

**One-time operation does not mean disposable implementation.** Legacy production
cutover happens once, but source validation, rehearsal and reconciliation need
maintained tools and regression tests until the legacy workflow is retired.

## Maintained commands

Inspect the CLI without starting a database or worker:

```bash
python3 -m scripts.migration.legacy.rehearse --help
python3 -m scripts.migration.legacy.prepare_sources --help
python3 -m scripts.migration.legacy.reconcile_exports --help
python3 -m scripts.testing.legacy_qc --help
```

Use the [legacy migration guide](migration/legacy/README.md) for source/output
contracts and the [QC verification guide](testing/README.md) for prepared worker
execution. Imports, `--help`, source preparation and export reconciliation use
the standard library. Both rehearsal modes (audit and `--apply`) execute the
application's importer and require the frontend Python environment. Actual QC
runs need Docker and the worker's geospatial dependencies.

Inside an existing frontend/worker image, set the repository as the working
directory before invoking a script module:

```bash
docker compose -f docker/compose.local.yaml exec \
  -w /usr/local/src/copernicus_quality_tools \
  frontend python3 -m scripts.migration.legacy.rehearse --help
```

Only committed scripts are available in source-archive release images. The
checkout-mounted development stack sees the local scripts immediately.

## What belongs in QC Tool testing

| Test type | Owner | Execution |
| --- | --- | --- |
| Tool input/provenance/isolation contracts | `scripts/tests/` | Host `unittest`, collected by the offline CI job |
| Raster/vector and archive-security behavior | `src/qc_tool/test/` | Existing worker regression suite with its GDAL/PostGIS environment |
| Database policy/import/model invariants | `src/qc_tool/database/tests/` | Existing host/integration groups |
| Frontend access, upload, submission and UI behavior | Frontend account/dashboard test packages | Existing Django/JavaScript groups |
| Production/v3 compatibility on actual deliveries | `scripts/testing/` and private evidence | Explicit paired integration runs; never triggered by the offline host suite |

Strict compatibility means identical production/v3 pass/fail outcomes for the
same delivery, original specification and production dependency profile. The
damaged-ZIP fix is the only permitted behavior difference. Archived reports
from older workers and a current diagnostic run alone do not prove that
contract. Differences and missing reference evidence must remain visible.

Do not promote a one-off investigation into CI by importing or executing every
Python file in `scripts/`. Some historical files generate delivery metadata or
contact a production service. Collect `scripts/tests/` explicitly.

## Proposed deletions

These files are retained in the folders below. The proposals do not delete them.

| Candidate | Why removal is reasonable | Condition before removal |
| --- | --- | --- |
| `obsolete/wiki/crawl_sitemap.py` and `generate_sitemap.py` | Two unreferenced wiki sitemap implementations; neither builds the current docs. `docs/_config.yml` already uses `jekyll-sitemap`. | Confirm no external operator still uses the old wiki workflow, then remove both together. |
| `obsolete/wiki/sitemap.xml` | Generated historical wiki output can be regenerated; it is not current documentation source. | Remove with the wiki generators. |
| `obsolete/wiki/sidebar.md` | Empty historical artifact with no callers. | Remove with the obsolete wiki files. |
| `one_off/clc2024/delivery_list.json` | Captured production delivery metadata, not a synthetic test fixture or maintained catalog. | Preserve any required investigation evidence privately; pass a private list explicitly to the diagnostic. |
| `one_off/clc2024/generate_metadata.py` | Product-specific embedded templates and import-time file writes make it unsuitable as a general maintained command or regression test. | Confirm the historical preparation is complete and any required templates have an owning maintained workflow. |
| `catalog/check_tile_codes.py` | Fixed product-family/step/length assumptions can drift from current product-unit validation. | Move any still-needed assertions into focused tests of the real product-unit contract before retiring this diagnostic. |
| `catalog/naming_examples.py` | Heuristic regex substitutions and direct parsEO parsing are different from the application's naming integration. | Preserve useful explicit cases in tests of the actual naming adapter before retiring the example generator. |

Keep the migration helpers, their unit tests, the worker evidence runner and
boundary-generation tools. The CLC gap analysis remains a manual diagnostic
while that investigation is useful; archive/remove it when its owner closes the
investigation and preserves the relevant findings.

## Adding or maintaining a tool

1. Put it in the owning purpose directory. Use a verb/object name such as
   `reconcile_exports.py`; keep dates, delivery IDs and machine paths in private
   run configuration or evidence.
2. State its purpose, lifecycle, dependencies, inputs, outputs and overwrite
   behavior in its module docstring and directory README.
3. Use explicit CLI inputs and repository-relative defaults. Keep normal
   imports free of operator actions, and guard execution with `main()`.
4. Put durable business logic in the application package; a script should adapt
   an operator command to that logic rather than create another importer/check.
5. Add meaningful contract tests under `scripts/tests/<purpose>/` for maintained
   tools. Production access, large delivery downloads and expensive real QC
   remain explicit integration verification.
6. Keep product specifications and uploaded snapshots unchanged. Put integration
   configuration outside those bytes, and keep production credentials/captures
   out of the source tree.
7. Update invocation examples, local links and callers when moving a command.
   Use the new module names directly; do not retain duplicate compatibility
   wrappers for internal scripts without an identified external caller.

See [Testing](../docs/development/testing.md),
[Repository layout](../docs/architecture/repository-layout.md) and the
[database lifecycle](../src/qc_tool/database/README.md) for application-wide rules.
