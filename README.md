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

(1) install docker
```
sudo apt install docker.io docker-compose
```
(2) get the latest version of docker-compose (1.21 or higher)
```
sudo apt remove docker-compose
sudo curl -L https://github.com/docker/compose/releases/download/1.21.2/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
docker-compose --version
```

(3) get the source code from github and go to the copernicus_quality_tools/docker directory
```
git clone https://github.com/eea/copernicus_quality_tools
cd copernicus_quality_tools/docker
```

(4) Configure the directory for uploaded .gdb and .tif files by editing the hidden .env file in copernicus_quality_tools/docker: 
```
nano .env
```
The .env file looks like this:
```
WPS_PORT=5000
WPS_DIR=/mnt/wps
INCOMING_DIR=/mnt/wps/incoming
WPS_URL=http://qc_tool_wps:5000/wps
WPS_OUTPUT_URL=http://qc_tool_wps:5000/wps/output
PG_DATABASE_NAME=qc_tool_db
PG_HOST=qc_tool_postgis

FRONTEND_PORT=8000

WPS_MOUNT=/mnt/pracovni-archiv-01/projects/cop15m/volume-igor
```
In the .env file, set WPS_MOUNT in the last line to a directory with read and write permissions on your system.

(5) Build the docker containers and run the application
```
sudo docker-compose build --no-cache
sudo docker-compose up
```

The application should be running in a docker container at http://localhost:8000 in your browser.

The Postgres database and WPS service will be running on a local ip-address, for example on 172.21.0.3 and 172.21.0.4

* Note: docker-compose version 3 file format is used. In case of errors, please upgrade to a newer version of docker and docker-compose software.

## Development Setup when docker images are already built:
### in this setup, local changes in the source code will immediately take effect in the docker.
```
git clone https://github.com/eea/copernicus_quality_tools
export WPS_MOUNT=${PWD}
cd copernicus_quality_tools/docker
docker-compose run -v $WPS_MOUNT/copernicus_quality_tools:/usr/local/src/copernicus_quality_tools -d --use-aliases qc_tool_wps
docker-compose run -v $WPS_MOUNT/copernicus_quality_tools:/usr/local/src/copernicus_quality_tools -d --use-aliases qc_tool_postgis
docker-compose run -v $WPS_MOUNT/copernicus_quality_tools:/usr/local/src/copernicus_quality_tools -d --use-aliases qc_tool_frontend
docker inspect -f '{{.Name}} - {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $(docker ps -q)

```
The docker inspect command shows the local ip addresses of the docker containers, for example:
```
/docker_qc_tool_postgis_run_5 - 172.21.0.4
/docker_qc_tool_wps_run_7 - 172.21.0.3
/docker_qc_tool_frontend_run_9 - 172.21.0.2
```
* Check the ip address of the docker_qc_tool_frontend_ container (in this case it is 172.21.0.2)
* The application will be running on http://172.21.0.2:8000 in your browser where 172.21.0.2 is the "ip address" and 8000 is the "port number"
* NOTE: depending on your setup, the ip can be http://172.21.0.1 or http://172.21.0.2 or other. the output of the docker inspect command gives you the correct ip addresses on your host.
