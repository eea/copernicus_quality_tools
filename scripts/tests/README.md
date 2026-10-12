# Maintainer-tool regression tests

These are repeatable offline tests for maintained operator tools. They use
synthetic records and temporary files; no production records, credentials,
application databases or real QC jobs are needed. Git is required for the
protected-source fixture tests. Python 3.11 or newer and the standard library
are sufficient.

Run from the repository root:

```bash
python3 -m unittest discover -s scripts/tests -t . -v

# Focused groups
python3 -m unittest discover -s scripts/tests/migration -t . -v
python3 -m unittest discover -s scripts/tests/testing -t . -v
```

The **Maintainer tools (offline)** CI job collects this directory explicitly.
`migration/` covers source preparation, fresh-target rehearsal/isolation and
export reconciliation. `testing/` covers the worker evidence runner's input,
classification and source-provenance contracts.

Application unit/integration tests remain with their owning packages under
`src/qc_tool/`. Historical investigations and generated outputs are not test
fixtures; do not import all files in `scripts/` for test discovery. See the
[application testing guide](../../docs/development/testing.md) for the worker,
frontend, JavaScript and database suites.
