# EEA Copernicus QC Tool

The application is composed of:
* Front-end user interface, alias web console;
* Web Processing Service (WPS);
* Postgis database;

# Prerequisities

* docker version 1.13 or higher, see https://docs.docker.com/install/linux/docker-ce/ubuntu/;
* docker-compose 1.21 or higher, see https://docs.docker.com/compose/install/#install-compose;

* Note: docker-compose version 3 file format is used. In case of errors, please upgrade to a newer version.

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

(4) If you want to utilize source codes cloned in the step (1) you can overlay source codes already built inside the image.  You will apply docker bind mount.  For advice see the first item in section `volumes:` in [docker-compose.igor.yml](docker/docker-compose.igor.yml).

(5) Run the application
```
sudo docker-compose -f ./docker-compose.yours.yml up
```

(6) You can reach the web console at any host address and port 8000.  For example, if you run the browser at the same host as docker containers, you can reach the application at http://localhost:8000.


# Run tests

There are already some automated tests at `src/qc_tool/test`.
The tests are still under development.
If you want to experiment with tests, there are instructions in [NOTES.txt](src/qc_tool/test/NOTES.txt).
