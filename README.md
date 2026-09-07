# EEA CLMS QC Tool

The application is composed of:
* Front-end user interface, alias web console;
* Worker Service;

# Documentation

Documentation of the QC tool, and specification of supported QA checks is available at https://github.com/eea/copernicus_quality_tools/wiki

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

(3) (Optional) Adjust the file `docker-compose.service_provider.yml` in accord with your environment.  For example see [docker/docker-compose.igor.yml](docker/docker-compose.igor.yml).  The environment variables are described in [docker/NOTES.environ.txt](docker/NOTES.environ.txt).  There is also `docker-compose.eea.yml` prepared targeting eea infrastructure with submission feature enabled.

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
For advice see the example docker compose configuration [docker-compose.igor.yml](docker/docker-compose.igor.yml).

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

QA check configurations for Copernicus products are defined in the [product_definitions](product_definitions) directory. Each product definition .json file contains a list of parametrized checks. For QC tool setup with editable product definitions, see instructions in [docker/NOTES.product_definitions](docker/NOTES.product_definitions.md).
