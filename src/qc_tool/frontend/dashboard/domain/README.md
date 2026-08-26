# Dashboard domain models

This directory holds durable business records. Django still registers every
model under the historical `dashboard` app label, so table names, migrations,
content types, and permissions remain stable.

## Packages

- `accounts/` owns token and profile records that remain under the historical
  `dashboard` app label for migration compatibility.
- `storage/` owns remote delivery storage coordinates.
- `deliveries/` owns the one-ZIP upload aggregate.
- `jobs/` owns persisted QC history, provenance, and the worker queue seam.
- `catalog/` owns products, immutable QC-definition snapshots, versioned
  releases, explicit definition links, and authoritative expected AOIs.
- `submissions/` owns publication records and the current plus historical
  state of duplicate-AOI decisions.

Each model concept has its own module. Package `__init__.py` files are the
public import boundary; application code should import models from
`qc_tool.frontend.dashboard.models` unless it is extending this domain layer.

Keep workflow orchestration out of model modules. Cross-record transactions,
publication, catalog synchronization, and conflict resolution belong in the
matching `services/` package. Models enforce local invariants and historical
immutability.
