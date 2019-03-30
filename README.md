# EEA Copernicus QC Tool

The application is composed of:
* Front-end user interface, alias web console;
* Worker Service (WPS);
* Postgis database;

# Prerequisities

* docker version 1.13 or higher, see https://docs.docker.com/install/linux/docker-ce/ubuntu/;
* docker-compose 1.21 or higher, see https://docs.docker.com/compose/install/#install-compose;

* Note: docker-compose version 3 file format is used. In case of errors, please upgrade to a newer version.

* For installation on Windows, see [docker/NOTES.windows](docker/NOTES.windows.md).

# Run the application

(1) clone the source code from github.

```
git clone https://github.com/eea/copernicus_quality_tools
```

(2) go to docker directory.

```
cd copernicus_quality_tools/docker
```

(3) Create a copy of `docker-compose.service_provider.yml` and adjust the copy in accord with your environment.  For example see `docker-compose.igor.yml`.  The environment variables are described in [docker/NOTES.environ.txt](docker/NOTES.environ.txt).  There is also `docker-compose.eea.yml` prepared targeting eea infrastructure with submission feature enabled.

(4) Run the application

```
sudo docker-compose -f ./docker-compose.service_provider.yml -p qc_tool_app up
```

(5) You can reach the web console at any host address and port 8000.  For example, if you run the browser at the same host as docker containers, you can reach the application at http://localhost:8000.

(6) For initial signing in use user name `guest` and password `guest`.

# Documentation

Documentation of the QC tool, and specification of supported QA checks is available at https://github.com/eea/copernicus_quality_tools/wiki

# For developers

If you want to propagate your local source code into running containers you may apply docker bind mount.
Such a way you overlay the source code already built in the image at `/usr/local/src/copernicus_quality_tools`.
For advice see the example docker compose configuration [docker-compose.igor.yml](docker/docker-compose.igor.yml).

There are already some automated tests at `src/qc_tool/test`.
See the instructions in [NOTES.txt](src/qc_tool/test/NOTES.txt).

The qc_tool_frontend service uses sqlite database originally located at `/var/lib/qc_tool/frontend.sqlite`.
The initial database structure is made during docker build.
The `service_provider` and `eea` configurations use named volumes for persisting such database.
You are free to copy the database to other persistent location, however you must ensure setting up FRONTEND_DB_PATH properly.

# Product definitions

QA check configurations for Copernicus products are defined in the [product_definitions](product_definitions) directory. Each product definition .json file contains a list of parametrized checks. For QC tool setup with editable product definitions, see instructions in [docker/README.product_definitions](docker/README.product_definitions.md).
