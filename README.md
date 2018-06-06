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

(4) Configure the directory for uploading .gdb and .tif files by editing the hidden .env file in copernicus_quality_tools/docker: 
```
nano .env
```
Edit the .env file to look like this:
```
WPS_PORT=5000
WPS_DIR=/mnt/wps
INCOMING_DIR=/mnt/wps/incoming
WPS_URL=http://qc_tool_wps:5000/wps
WPS_OUTPUT_URL=http://qc_tool_wps:5000/wps/output
PG_DATABASE_NAME=qc_tool_db
PG_HOST=qc_tool_postgis
FRONTEND_PORT=8000
WPS_MOUNT=/tmp
```
In the .env file, set *WPS_MOUNT* to a directory on your system with read and write permissions on your system. For example you can set *WPS_MOUNT=/home/jiri/qc_tool* if you have that folder.

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
  qc_tool_wps python3 -m unittest qc_tool.test.test_dummy
```

## Launching All Docker Containers via command-line
---------------------------------------------------
(1) Start the postgis container. MY_QC_TOOL_HOME must be the absolute path to your copernicus_quality_tools folder
```
MY_QC_TOOL_HOME=/mnt/pracovni-archiv-01/projects/cop15m/volume-new/copernicus_quality_tools
docker run --rm --publish 15432:5432 --name=qc_tool_postgis --tty --interactive qc_tool_postgis
```
(2) Switch to a second terminal window and start the wps container
```
MY_QC_TOOL_HOME=/mnt/pracovni-archiv-01/projects/cop15m/volume-new/copernicus_quality_tools
docker run --rm \
  --interactive --tty \
  --name=qc_tool_wps \
  --link=qc_tool_postgis \
  --volume $MY_QC_TOOL_HOME:/usr/local/src/copernicus_quality_tools \
  qc_tool_wps
```

(3) Switch to a third terminal window and start the frontend. MY_QC_TOOL_HOME must be the absolute path to your copernicus_quality_tools folder
```
MY_QC_TOOL_HOME=/mnt/pracovni-archiv-01/projects/cop15m/volume-new/copernicus_quality_tools
docker run --rm \
  --interactive --tty \
  --publish 8000:8000 \
  --name=qc_tool_frontend \
  --link=qc_tool_wps \
  --volume $MY_QC_TOOL_HOME:/usr/local/src/copernicus_quality_tools \
  qc_tool_frontend
```
