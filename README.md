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
mkdir $HOME/github
cd $HOME/github
git clone https://github.com/eea/copernicus_quality_tools
docker build copernicus_quality_tools/docker -f copernicus_quality_tools/docker/Dockerfile.phusion -t ubucop
sh $HOME/github/copernicus_quality_tools/docker/run_docker_local.sh $HOME/github $HOME/github/copernicus_quality_tools/testing_data

```

The application should be running in a docker container at http://172.17.0.2:8000 in your browser.

The WPS service should be running at http://172.17.0.2:5000 in your browser.

* Note: the run_docker_local.sh script has two arguments. The first one is the parent
directory of the folder cloned from Github. The second one is the path where the qc
tool looks for .gdb or .tif files to be checked and where the user can add new files.
