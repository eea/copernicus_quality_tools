# Copernicus QC Tool - open source version
Here you can find source code of the EEA Copernicus QC Tool.
The application will consist of:
* Front-end user interface
* Back-end Web Processing Service (WPS)
* Configurable quality Control checking functions for raster and vector products
* Copernicus data product Quality Assurance configurations
* Application deployment tools based on docker

# QC Tool Checking Environment
Steps to install the code and run it (tested on Ubuntu Linux 16.04):

(1) install docker version 1.13 or higher

(see https://docs.docker.com/install/linux/docker-ce/ubuntu/)

(2) get the latest version of docker-compose (1.21 or higher)

(see https://docs.docker.com/compose/install/#install-compose)

(3) get the source code from github and go to the copernicus_quality_tools/docker directory
```
git clone https://github.com/eea/copernicus_quality_tools
cd copernicus_quality_tools/docker
```

(4) Create a new file `docker-compose.yml` for your local deployment. See the files `docker-compose.igor.yml` and `docker-compose.jiri.yml`
as an example. The most important setting is to edit the volumes. the `/mnt/wps` volume should be mounted to a writable volume on your system. The environment variables which can be set in docker-compose.yml are explained in the [NOTES.environ.txt](docker/NOTES.environ.txt) document.

(5) Build the docker containers and run the application
```
sudo docker-compose build --no-cache
sudo docker-compose up
```

The application should be running in a docker container at http://localhost:8000 in your browser.

The Postgres database and WPS service will be running on a local ip-address, for example on 172.21.0.3 and 172.21.0.4

* Note: docker-compose version 3 file format is used. In case of errors, please upgrade to a newer version of docker and docker-compose software.

## Testing Environment Setup
----------------------------
### in this setup, local changes in the source code will immediately take effect in the docker. For running unit test you first need to start-up the
qc_tool_postgis docker and then start the qc_tool_wps in testing mode.
```
git clone https://github.com/eea/copernicus_quality_tools
cd copernicus_quality_tools/docker

docker build --file=Dockerfile.postgis --tag=qc_tool_postgis .
docker build --file=Dockerfile.wps --tag=qc_tool_wps .
docker build --file=Dockerfile.frontend --tag=qc_tool_frontend .

docker run --rm --publish 15432:5432 --name=qc_tool_postgis --tty --interactive qc_tool_postgis
```

## switch to a new terminal window and then run:
```
MY_QC_TOOL_HOME=/mnt/pracovni-archiv-01/projects/cop15m/volume-new/copernicus_quality_tools (set this to the actual folder with your copernicus_quality_tools source code!)
docker run --rm \
  --interactive --tty \
  --name=qc_tool_wps \
  --link=qc_tool_postgis \
  --volume=$MY_QC_TOOL_HOME:/usr/local/src/copernicus_quality_tools \
  qc_tool_wps python3 -m unittest qc_tool.test.test_vector_check
```
