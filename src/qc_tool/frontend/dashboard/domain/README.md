# Dashboard domain models

This directory holds catalog, execution, storage and publication records.
Django discovers these models through `dashboard.models` under the `dashboard`
app label. Explicit `Meta.db_table` names describe business responsibility;
the [application schema](../../../database/SCHEMA.md) owns their table inventory
and persistence boundaries. Account models belong to `accounts.models`.

## Packages

- `storage/` owns remote delivery storage coordinates.
- `deliveries/` owns the one-ZIP upload aggregate.
- `jobs/` owns persisted QC history, provenance, and the worker queue seam.
- `catalog/` owns products, immutable QC-definition snapshots, versioned
  releases, explicit definition links, and authoritative expected product units.
- `submissions/` owns publication records and the current plus historical
  state of duplicate-product unit decisions.

Each model concept has its own module. Package `__init__.py` files are the
public import boundary; application code should import models from
`qc_tool.frontend.dashboard.models` unless it is extending this domain layer.

Keep workflow orchestration out of model modules. Cross-record transactions,
publication, catalog synchronization, and conflict resolution belong in the
matching `services/` package. Models enforce local invariants and historical
immutability.
