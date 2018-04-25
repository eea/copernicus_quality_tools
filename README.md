# Copernicus QC Tool - open source version
Here you can find source code of the EEA Copernicus QC Tool.
The application will consist of:
* Front-end user interface
* Back-end Web Processing Service (WPS)
* Configurable quality Control checking functions for raster and vector products
* Copernicus data product Quality Assurance configurations
* Application deployment tools based on docker

# QC Tool USER-FACING application
Steps to install the code and run it
```
git clone https://github.com/eea/copernicus_quality_tools
cd copernicus_quality_tools
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
pip install requests
cd src/qc_tool/frontend
python manage.py runserver
```

The application should be running at http://127.0.0.1:8000 in your browser
