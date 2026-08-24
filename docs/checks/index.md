---
title: Checks
has_children: true
nav_order: 8
---
# Checks

This section documents product-facing QC check behavior. Check implementations
live in `src/qc_tool/vector/` and `src/qc_tool/raster/`; product recipes select
and parameterize them from `product_definitions/`.

- [Vector checks](vector-checks.md)

Raster check documentation is not yet complete. Consult the reviewed product
specification and implementation together, and add the missing human-readable
reference when changing raster behavior.
