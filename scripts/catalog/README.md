# Catalog diagnostics

These commands read product specification JSONs and print findings. They never
rewrite specifications. They are manual legacy diagnostics; neither establishes
that a delivery passes QC or replaces the application's product-unit/naming
contracts.

Run from the repository root:

```bash
python3 -m scripts.catalog.check_tile_codes --help
python3 -m scripts.catalog.naming_examples --help

python3 -m scripts.catalog.check_tile_codes \
  --products-dir /path/to/original-specifications

python3 -m scripts.catalog.naming_examples \
  --products-dir /path/to/original-specifications
```

Omit `--products-dir` to read this checkout's `product_definitions/`, independent
of the script's nested location.

| Command | Dependencies | What the output means |
| --- | --- | --- |
| `check_tile_codes` | Standard library | Reports allowlist entries whose length is not six characters in the second recipe step, for the historical CLCplus/HRLVLCC/HRLNVLCC families. It does not validate all product-unit types or schemas. |
| `naming_examples` | parsEO | Uses fixed substitutions in selected CLMS naming patterns, then calls the legacy `parse_auto()` API. Printed OK/FAILED describes those constructed examples, not the application's naming adapter or real delivery QC. |

`--help` works without loading parsEO. Neither diagnostic is an automated test
gate, and their printed findings are not a reliable pass/fail exit-code contract.
Useful explicit cases should become tests of the real application contract before
the diagnostics are retired. See the [removal proposals](../README.md#proposed-deletions).
