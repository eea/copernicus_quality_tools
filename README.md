# EEA CLMS QC Tool

The application is composed of:
* Front-end user interface, alias web console;
* Worker Service;

# Documentation

Use the [documentation in this repository](docs/index.md), including the
[QA check reference](docs/checks/index.md). Read the files from the same source
revision as the application; the historical wiki is not maintained with the code.

# Reporting Issues

Please report any issues in the QC tool via GitHub:

* Go to https://github.com/eea/copernicus_quality_tools/issues and click *New Issue*.
* Sign-in with your GitHub account (or create a new GitHub account if you don't have one).
* Describe your issue. When describing an issue, please include the QC tool version and steps to reproduce.
* The development team will investigate the issue and get back to you.

# Installation

Use current supported Docker Engine and Docker Compose. Follow the
[deployment guide](docs/deployment/index.md) for reviewed image digests,
secrets, HTTPS ingress and explicit database initialization, or the
[local workflow](docs/getting-started/local-development.md) for development.

Each maintained deployment profile is one complete Compose file. Choose
[`docker/docker-compose.eea.yml`](docker/docker-compose.eea.yml) for named volumes
or [`docker/compose.eea-storage.yaml`](docker/compose.eea-storage.yaml) for
operator-provisioned Azure/EEA host storage, and select that file alone. Local
and SQLite/provider profiles are self-contained too. A private environment file
supplies deployment values; no additional Compose file, generator or wrapper is
required. Rancher importer/version prerequisites still require verification on
the target deployment, as described in the [deployment guide](docs/deployment/index.md#rancher-import).

The maintained profiles select a canonical separated storage layout. New
`qc_tool_v3_*` application volumes and `postgres17_data_v3` retain older volumes
without adopting their data. Workers read incoming deliveries, specifications
and boundaries through read-only mounts; private frontend state and submitted
publications are absent from worker mounts. See
[storage paths and handoff](docs/deployment/eea-storage.md).

Production startup checks a matching schema read-only. An entirely empty new
installation needs an explicit `database plan|apply|check` procedure and a
separately created administrator; starting Compose does not initialize it.
Never point PostgreSQL 17 at an existing PostgreSQL 14 data directory or reset
an occupied database to make a deployment start. Preserve the old database and
files until a separate logical restore and coordinated file handoff are verified.

For Windows host setup, see [Windows notes](docker/NOTES.windows.md).

# For developers

If you want to propagate your local source code into running containers you may apply docker bind mount.
Such a way you overlay the source code already built in the image at `/usr/local/src/copernicus_quality_tools`.
For configuration advice, see the [deployment guide](docs/deployment/index.md).

There are already some automated tests at `src/qc_tool/test`.
See the instructions in [NOTES.txt](src/qc_tool/test/NOTES.txt).

Maintainer commands are grouped by purpose under [`scripts/`](scripts/README.md).
The catalog distinguishes repeatable tests, manual diagnostics and historical
experiments, and lists proposed removals. See the [testing guide](docs/development/testing.md)
for the host, worker and frontend suites.

The application-wide database package lives in
[`src/qc_tool/database/`](src/qc_tool/database/README.md). It owns the committed
models-only policy, initialization command and schema checks.
**v3.0.0 contains no migration framework, definitions, initial snapshots or legacy
converter.** `database plan|check` inspects the current schema without changing it.
`database apply` initializes an entirely empty database from current models,
including in production, and leaves a complete matching database unchanged.
It refuses partial or foreign schemas and detected model drift. Schema changes
require a new target and a separately reviewed data transfer; startup does not upgrade or
reset existing databases.

Legacy conversion is a private manual cutover operation outside the application.
Use the [manual restore guide](src/qc_tool/database/MANUAL_RESTORE.md) for a prepared
database artifact, and the [database guide](src/qc_tool/database/README.md) before
changing models, selecting persistent volumes or deploying. Initial migration
definitions may be introduced only in a separately reviewed **v3.0.1-or-later**
release with an explicit transition plan.


# Demo installation

The demonstration service is publicly available at:
https://qc-copernicus.eea.europa.eu/. Access credentials are managed by the
service operator and are intentionally not stored in this repository.

# Product definitions

The product catalog starts empty. Administrators upload selected JSON specifications
through **Products → Upload specification**, then assign their products to users.
The [product_definitions](product_definitions) directory contains reference QC
recipes; startup does not import them. Each JSON file contains a list of
parameterized checks. See [Managing product specifications](docker/NOTES.product_definitions.md).
