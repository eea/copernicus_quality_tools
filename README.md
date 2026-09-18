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

# Prerequisities

* docker version 1.13 or higher, see https://docs.docker.com/install/linux/docker-ce/ubuntu/;
* docker-compose 1.21 or higher, see https://docs.docker.com/compose/install/#install-compose;

* Note: docker-compose version 3 file format is used. In case of errors, please upgrade to a newer version.

* For installation on Windows, see [docker/NOTES.windows](docker/NOTES.windows.md).

# Run the application

(1) Go to the [latest release](https://github.com/eea/copernicus_quality_tools/releases)

(2) Download the file `docker-compose.service_provider.yml`

(3) (Optional) Adjust the file `docker-compose.service_provider.yml` in accord with your environment. Follow the [deployment guide](docs/deployment/index.md) and [environment-variable reference](docs/reference/environment-variables.md). There is also `docker-compose.eea.yml` prepared targeting eea infrastructure with submission feature enabled.

(4) Run the application

```
sudo docker-compose -f ./docker-compose.service_provider.yml -p qc_tool_app up --scale worker=4
```

(5) You can reach the web console at any host address and port 8000.  For example, if you run the browser at the same host as docker containers, you can reach the application at http://localhost:8000.

(6) Create the first administrator through Django's `createsuperuser` command,
or use your deployment's identity/bootstrap process. Never configure a shared
or predictable password in production.

(7) To upgrade to a new release, run:
```
sudo docker-compose -f ./docker-compose.service_provider.yml -p qc_tool_app pull
```
This will instruct docker to re-download the latest QC tool release images from docker hub repository.

# For developers

If you want to propagate your local source code into running containers you may apply docker bind mount.
Such a way you overlay the source code already built in the image at `/usr/local/src/copernicus_quality_tools`.
For configuration advice, see the [deployment guide](docs/deployment/index.md).

There are already some automated tests at `src/qc_tool/test`.
See the instructions in [NOTES.txt](src/qc_tool/test/NOTES.txt).

The application-wide database package lives in
[`src/qc_tool/database/`](src/qc_tool/database/README.md). It owns the committed
schema history, release policy, deployment command, checks and migration runbook.
The release policy determines the workflow: `draft` schemas are developed from
models without migration files; release freeze creates the first versioned
snapshots. Released schemas evolve through committed migrations applied in one
deployment job, and production startup checks that they are current. Legacy
data transfers use a separate import procedure into a fresh target database.
See the [migration runbook](src/qc_tool/database/MIGRATIONS.md) before changing
models, selecting persistent volumes or deploying an upgrade.


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
