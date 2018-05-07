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
sudo docker-compose up

```

The application should be running in a docker container at http://127.0.0.1:8000 in your browser.

The WPS service should be running at http://127.0.0.1:5000 in your browser.

* Note: the docker-compose.yml file is used for the setup. The default directory for storing .gdb and .tif files is copernicus_quality_tools/testing_data. You can change this directory by editing the volumes settings in the docker-compose.yml file. 
