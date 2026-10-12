# Legacy migration tools

These operator tools support the separate legacy data cutover. The application
owns the importer under `src/qc_tool/database/legacy/` and the whole-app
`database plan|apply|check` command. Read the
[database lifecycle](../../../src/qc_tool/database/README.md) and
[migration runbook](../../../src/qc_tool/database/MIGRATIONS.md) before changing
persistence behavior.

Run modules from the repository root. The source contract, access/password
policy and reconciliation evidence are documented in the
[local rehearsal runbook](../../../src/qc_tool/database/LOCAL_LEGACY_REHEARSAL.md).

| Command | Inputs | Outputs and effect |
| --- | --- | --- |
| `prepare_sources` | Older plain SQL dump, complete delivery/job CSVs, current user JSON | A new private directory containing unchanged source copies, a provenance manifest and mixed-history interchange; no database connection. |
| `rehearse` | Plain SQL dump or reviewed mixed-history interchange; optional access map | A new private audit directory. `--apply` additionally creates a fresh offline SQLite target through the existing database command, imports and reconciles it. |
| `reconcile_exports` | Original delivery/job CSVs, XLSX exports; optional SQL dump for owner mapping | Aggregate diagnostics and SHA-256 fingerprints on stdout; reads source files without rewriting them. |

Preparation and rehearsal output directories must not exist. Rehearsals are
repeatable by choosing a new directory each time. They never reset an existing
database, and the conversion does not replace the application's migration policy.

```bash
# Audit only; requires the frontend Python environment for child commands.
python3 -m scripts.migration.legacy.rehearse /private/production.sql \
  --output-dir /private/new-audit

# Explicit fresh local import; this writes only the new rehearsal target.
python3 -m scripts.migration.legacy.rehearse /private/production.sql \
  --apply --output-dir /private/new-import

# Compare the available web exports without replacing migration sources.
python3 -m scripts.migration.legacy.reconcile_exports \
  --delivery-csv /private/dashboard_delivery.csv \
  --job-csv /private/dashboard_job.csv \
  /private/deliveries-export.xlsx
```

A mixed-history interchange is not a coherent production backup. Web user
captures do not establish password hashes; preparation produces unusable target
passwords, as described in the owning runbook. Private captures remain outside
Git. The maintained [unit tests](../../tests/migration/) use synthetic data and
never run a production cutover.
