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

```
sudo apt install docker.io docker-compose

git clone https://github.com/eea/copernicus_quality_tools
cd copernicus_quality_tools/docker
sudo docker-compose build --no-cache qc_tool_wps
sudo docker-compose build --no-cache qc_tool_postgis
sudo docker-compose build --no-cache qc_tool_frontend
sudo docker-compose up

```

The application should be running in a docker container at http://127.0.0.1:8000 in your browser.

The WPS service should be running at http://127.0.0.1:5000 in your browser.

* Note: the docker-compose.yml file and the .env file are used for setup configuration. You need to change the WPS_MOUNT variable in the .env file to an existing directory with write permissions on your system. 
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
