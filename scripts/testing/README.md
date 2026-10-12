# Worker verification tooling

[`legacy_qc.py`](legacy_qc.py) runs captured uploaded ZIP deliveries through an
already isolated worker and saves actual JSON/PDF evidence. It does not create
frontend delivery/job entries, upload or submit deliveries, or modify production
records and specifications.

Run from the repository root:

```bash
python3 -m scripts.testing.legacy_qc --help

python3 -m scripts.testing.legacy_qc \
  --evidence-root /private/prepared-evidence \
  --container qc-tool-isolated-verification \
  --current-checks \
  --specification-dir /private/prepared-evidence/production-specifications
```

The worker must already have the required read-only source/input/specification/
boundary mounts and separate writable scratch/PostGIS storage. The runner
validates that configuration; it does not create the runtime. See the
[full verification procedure](../../docs/development/legacy-qc-parity.md) for
the evidence layout, selection, runtime guards, exit statuses and limitations.

This is a repeatable integration tool, not an automatically executed unit test.
Archived comparisons are diagnostics. Strict production/v3 compatibility
requires paired reference/candidate results on identical input bytes, original
specifications and the production dependency profile. The damaged-ZIP fix is
the sole permitted behavior difference; differences or missing reference
evidence prevent a parity claim.

Unit tests of selection, provenance, classification and source guards live in
[`../tests/testing/`](../tests/testing/). Those tests use synthetic/temp inputs
and mocked workers, and they cannot certify real product compatibility.
