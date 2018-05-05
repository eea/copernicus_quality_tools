# Copernicus QC Tool - open source version
Here you can find source code of the EEA Copernicus QC Tool.
The application will consist of:
* Front-end user interface
* Back-end Web Processing Service (WPS)
* Configurable quality Control checking functions for raster and vector products
* Copernicus data product Quality Assurance configurations
* Application deployment tools based on docker

# QC Tool Checking Environment
Steps to install the code and run it

```
git clone https://github.com/eea/copernicus_quality_tools
sudo docker build copernicus_quality_tools/docker -f Dockerfile.phusion -t ubucop
sh ./copernicus_quality_tools/docker/run_docker_local.sh $(pwd) $(pwd)/copernicus_quality_tools/testing_data

```

The application should be running in a docker container at http://172.17.0.2:8000:8000 in your browser

* Note: the run_docker_local.sh script has two arguments. The first one is the parent
directory of the folder cloned from Github. The second one is the path where the qc
tool looks for .gdb or .tiff files to be checked and where the user can add new files.
